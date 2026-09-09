"""数据持久化：MySQL 业务库 + SQLite 自动降级。

表：
- repair_orders  报修工单
- chat_logs      会话日志（含意图/耗时/是否转人工）

MySQL 不可用时自动落 SQLite（data/app.db），保证零配置演示。
测试可通过环境变量 DB_PATH 覆盖数据库文件（避免与运行中的服务抢锁）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .config import settings

_lock = threading.Lock()
_conn = None
_backend = "sqlite"


def _get_sqlite() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db_path = Path(os.environ.get("DB_PATH", str(settings.project_dir / "data" / "app.db")))
        db_path.parent.mkdir(exist_ok=True)
        _conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def _get_mysql():
    import pymysql
    return pymysql.connect(
        host=settings.mysql_host, port=settings.mysql_port,
        user=settings.mysql_user, password=settings.mysql_password,
        database=settings.mysql_db, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def init_db() -> None:
    """建表。优先 MySQL（需要已建库），失败则 SQLite。"""
    global _backend
    mysql_sql = """
    CREATE TABLE IF NOT EXISTS repair_orders (
        order_no VARCHAR(32) PRIMARY KEY,
        store_id VARCHAR(16), device VARCHAR(64), problem_desc VARCHAR(1024),
        priority VARCHAR(16), status VARCHAR(16), sla VARCHAR(64), created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) DEFAULT CHARSET=utf8mb4;
    CREATE TABLE IF NOT EXISTS chat_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64), user_id VARCHAR(64), store_id VARCHAR(16),
        query TEXT, intent VARCHAR(32), answer TEXT, handoff TINYINT,
        latency_ms INT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) DEFAULT CHARSET=utf8mb4;
    """
    sqlite_sql = """
    CREATE TABLE IF NOT EXISTS repair_orders (
        order_no TEXT PRIMARY KEY, store_id TEXT, device TEXT, problem_desc TEXT,
        priority TEXT, status TEXT, sla TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS chat_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT, user_id TEXT, store_id TEXT,
        query TEXT, intent TEXT, answer TEXT, handoff INTEGER,
        latency_ms INTEGER, created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """
    with _lock:
        if _backend == "mysql":
            try:
                c = _get_mysql()
                for stmt in mysql_sql.split(";"):
                    if stmt.strip():
                        with c.cursor() as cur:
                            cur.execute(stmt)
                c.commit()
                c.close()
                return
            except Exception:
                _backend = "sqlite"
        conn = _get_sqlite()
        conn.executescript(sqlite_sql)
        conn.commit()


def get_backend() -> str:
    return _backend


def repair_store(record: dict) -> None:
    with _lock:
        if _backend == "mysql":
            try:
                c = _get_mysql()
                with c.cursor() as cur:
                    cur.execute(
                        "INSERT INTO repair_orders (order_no,store_id,device,problem_desc,priority,status,sla) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (record["order_no"], record["store_id"], record["device"],
                         record["problem_desc"], record["priority"], record["status"], record["sla"]),
                    )
                c.commit()
                c.close()
                return
            except Exception:
                pass
        conn = _get_sqlite()
        conn.execute(
            "INSERT INTO repair_orders (order_no,store_id,device,problem_desc,priority,status,sla) "
            "VALUES (?,?,?,?,?,?,?)",
            (record["order_no"], record["store_id"], record["device"],
             record["problem_desc"], record["priority"], record["status"], record["sla"]),
        )
        conn.commit()


def save_chat_log(log: dict) -> None:
    with _lock:
        if _backend == "mysql":
            try:
                c = _get_mysql()
                with c.cursor() as cur:
                    cur.execute(
                        "INSERT INTO chat_logs (session_id,user_id,store_id,query,intent,answer,handoff,latency_ms) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (log["session_id"], log["user_id"], log["store_id"], log["query"],
                         log.get("intent", ""), log["answer"], int(log.get("handoff", False)),
                         int(log.get("latency_ms", 0))),
                    )
                c.commit()
                c.close()
                return
            except Exception:
                pass
        conn = _get_sqlite()
        conn.execute(
            "INSERT INTO chat_logs (session_id,user_id,store_id,query,intent,answer,handoff,latency_ms) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (log["session_id"], log["user_id"], log["store_id"], log["query"],
             log.get("intent", ""), log["answer"], int(log.get("handoff", False)),
             int(log.get("latency_ms", 0))),
        )
        conn.commit()


# ---------------- 工单状态机（报修闭环） ----------------
# 合法流转：已受理 → 已派单 → 维修中 → 已解决 → 已关闭（需店长确认）
REPAIR_FLOW: dict = {
    "已受理": ["已派单"],
    "已派单": ["维修中"],
    "维修中": ["已解决"],
    "已解决": ["已关闭"],
}
REPAIR_STATUS_ALL = set(REPAIR_FLOW) | {"已关闭"}


def _ensure_repair_columns() -> None:
    """兼容旧库：给 repair_orders 补 actor/confirmed 两列（MySQL/SQLite）。"""
    if _backend == "mysql":
        try:
            c = _get_mysql()
            with c.cursor() as cur:
                for ddl in ("actor VARCHAR(64) DEFAULT ''", "confirmed TINYINT DEFAULT 0"):
                    try:
                        cur.execute(f"ALTER TABLE repair_orders ADD COLUMN {ddl}")
                    except Exception:
                        pass  # 列已存在
            c.commit()
            c.close()
            return
        except Exception:
            pass
    conn = _get_sqlite()
    for ddl in ("actor TEXT DEFAULT ''", "confirmed INTEGER DEFAULT 0"):
        try:
            conn.execute(f"ALTER TABLE repair_orders ADD COLUMN {ddl}")
            conn.commit()
        except Exception:
            pass  # 列已存在


def get_repair(order_no: str) -> Optional[dict]:
    """按单号查工单。"""
    if _backend == "mysql":
        try:
            c = _get_mysql()
            with c.cursor() as cur:
                cur.execute("SELECT * FROM repair_orders WHERE order_no=%s", (order_no,))
                row = cur.fetchone()
            c.close()
            if row:
                row["confirmed"] = bool(row.get("confirmed"))
            return row
        except Exception:
            pass
    conn = _get_sqlite()
    row = conn.execute("SELECT * FROM repair_orders WHERE order_no=?", (order_no,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["confirmed"] = bool(d.get("confirmed"))
    return d


def list_repairs(store_id: Optional[str] = None, limit: int = 20) -> list:
    """工单列表（可按门店过滤），按创建时间倒序。"""
    if _backend == "mysql":
        try:
            c = _get_mysql()
            with c.cursor() as cur:
                if store_id:
                    cur.execute("SELECT * FROM repair_orders WHERE store_id=%s ORDER BY created_at DESC LIMIT %s",
                                (store_id, limit))
                else:
                    cur.execute("SELECT * FROM repair_orders ORDER BY created_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
            c.close()
            for r in rows:
                r["confirmed"] = bool(r.get("confirmed"))
            return rows
        except Exception:
            pass
    conn = _get_sqlite()
    if store_id:
        rows = conn.execute(
            "SELECT * FROM repair_orders WHERE store_id=? ORDER BY created_at DESC LIMIT ?",
            (store_id, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM repair_orders ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["confirmed"] = bool(d.get("confirmed"))
        out.append(d)
    return out


def update_repair_status(order_no: str, status: str, actor: str = "", confirm: bool = False) -> tuple:
    """推进工单状态。

    返回 (ok, message, record)。校验规则：
    - 目标状态必须在状态机白名单内；
    - 只能走到当前状态的下一状态（不可跳级、不可回退）；
    - 「已关闭」必须带 confirm=True（店长确认语义，防止维修工自说自话）。
    """
    _ensure_repair_columns()
    record = get_repair(order_no)
    if not record:
        return False, f"工单 {order_no} 不存在", None
    status = (status or "").strip()
    if status not in REPAIR_STATUS_ALL:
        return False, f"无效状态 {status}，可选：{'/'.join(sorted(REPAIR_STATUS_ALL))}", record
    current = record.get("status", "已受理")
    if status == current:
        return False, f"工单已是「{current}」状态", record
    if status not in REPAIR_FLOW.get(current, []):
        return False, f"非法流转：{current} → {status}（只能依次：{current} → {'/'.join(REPAIR_FLOW.get(current, [])) or '无'}）", record
    if status == "已关闭" and not confirm:
        return False, "关闭工单需要店长确认（confirm=true），维修工不能自行关闭", record

    if _backend == "mysql":
        try:
            c = _get_mysql()
            with c.cursor() as cur:
                cur.execute("UPDATE repair_orders SET status=%s, actor=%s, confirmed=%s WHERE order_no=%s",
                            (status, actor, 1 if status == "已关闭" else 0, order_no))
            c.commit()
            c.close()
        except Exception:
            pass
    conn = _get_sqlite()
    conn.execute("UPDATE repair_orders SET status=?, actor=?, confirmed=? WHERE order_no=?",
                 (status, actor, 1 if status == "已关闭" else 0, order_no))
    conn.commit()
    updated = get_repair(order_no)
    return True, f"工单 {order_no} 已更新为「{status}」", updated
