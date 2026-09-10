"""数据持久化：MySQL 业务库 + SQLite 自动降级。

表：
- repair_orders  报修工单
- chat_logs      会话日志（含意图/耗时/是否转人工）
- inventory      门店物料库存（支持 ERP 同步）
- promotions     促销政策（动态管理，支持有效期）
- stores         门店主数据（200+ 直营门店）
- devices        设备清单（按门店管理）
- staff          员工/维修工信息

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
    CREATE TABLE IF NOT EXISTS inventory (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        store_id VARCHAR(16), material VARCHAR(64), stock INT, unit VARCHAR(16),
        reorder_point INT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_store_material (store_id, material)
    ) DEFAULT CHARSET=utf8mb4;
    CREATE TABLE IF NOT EXISTS promotions (
        promo_code VARCHAR(16) PRIMARY KEY,
        name VARCHAR(128), rule TEXT, status VARCHAR(16),
        valid_from DATE, valid_until DATE, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) DEFAULT CHARSET=utf8mb4;
    CREATE TABLE IF NOT EXISTS stores (
        store_id VARCHAR(16) PRIMARY KEY,
        name VARCHAR(128), address VARCHAR(256), phone VARCHAR(32),
        manager VARCHAR(64), status VARCHAR(16) DEFAULT '营业中',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) DEFAULT CHARSET=utf8mb4;
    CREATE TABLE IF NOT EXISTS devices (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        device_id VARCHAR(32), store_id VARCHAR(16), device_type VARCHAR(64),
        brand VARCHAR(64), model VARCHAR(64), purchase_date DATE,
        warranty_until DATE, status VARCHAR(16) DEFAULT '正常',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) DEFAULT CHARSET=utf8mb4;
    CREATE TABLE IF NOT EXISTS staff (
        staff_id VARCHAR(32) PRIMARY KEY,
        name VARCHAR(64), role VARCHAR(32), phone VARCHAR(32),
        store_id VARCHAR(16), status VARCHAR(16) DEFAULT '在职',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT, material TEXT, stock INTEGER, unit TEXT,
        reorder_point INTEGER, updated_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(store_id, material)
    );
    CREATE TABLE IF NOT EXISTS promotions (
        promo_code TEXT PRIMARY KEY,
        name TEXT, rule TEXT, status TEXT,
        valid_from TEXT, valid_until TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS stores (
        store_id TEXT PRIMARY KEY,
        name TEXT, address TEXT, phone TEXT,
        manager TEXT, status TEXT DEFAULT '营业中',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT, store_id TEXT, device_type TEXT,
        brand TEXT, model TEXT, purchase_date TEXT,
        warranty_until TEXT, status TEXT DEFAULT '正常',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS staff (
        staff_id TEXT PRIMARY KEY,
        name TEXT, role TEXT, phone TEXT,
        store_id TEXT, status TEXT DEFAULT '在职',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """
    with _lock:
        # 先尝试 MySQL，成功则用 MySQL，失败则降级到 SQLite
        try:
            c = _get_mysql()
            _backend = "mysql"
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
            updated = get_repair(order_no)
            return True, f"工单 {order_no} 已更新为「{status}」", updated
        except Exception:
            pass
    conn = _get_sqlite()
    conn.execute("UPDATE repair_orders SET status=?, actor=?, confirmed=? WHERE order_no=?",
                 (status, actor, 1 if status == "已关闭" else 0, order_no))
    conn.commit()
    updated = get_repair(order_no)
    return True, f"工单 {order_no} 已更新为「{status}」", updated


# ---------------- 通用 CRUD 辅助 ----------------
def _execute(sql: str, params: tuple = (), fetch: str = "none"):
    """统一执行 SQL，自动适配 MySQL/SQLite。fetch: none/one/all"""
    if _backend == "mysql":
        try:
            c = _get_mysql()
            with c.cursor() as cur:
                cur.execute(sql, params)
                if fetch == "one":
                    row = cur.fetchone()
                elif fetch == "all":
                    row = cur.fetchall()
                else:
                    row = None
                    c.commit()
            c.close()
            return row
        except Exception as e:
            print(f"[db mysql error] {e}")
            return None
    conn = _get_sqlite()
    cur = conn.execute(sql, params)
    if fetch == "one":
        row = cur.fetchone()
        return dict(row) if row else None
    elif fetch == "all":
        return [dict(r) for r in cur.fetchall()]
    conn.commit()
    return None


# ---------------- inventory 物料库存 ----------------
def get_inventory(store_id: str, material: str) -> Optional[dict]:
    return _execute(
        "SELECT * FROM inventory WHERE store_id=%s AND material=%s" if _backend == "mysql"
        else "SELECT * FROM inventory WHERE store_id=? AND material=?",
        (store_id, material), fetch="one")


def list_inventory(store_id: Optional[str] = None, limit: int = 100) -> list:
    if store_id:
        return _execute(
            "SELECT * FROM inventory WHERE store_id=%s ORDER BY material LIMIT %s" if _backend == "mysql"
            else "SELECT * FROM inventory WHERE store_id=? ORDER BY material LIMIT ?",
            (store_id, limit), fetch="all") or []
    return _execute(
        "SELECT * FROM inventory ORDER BY store_id, material LIMIT %s" if _backend == "mysql"
        else "SELECT * FROM inventory ORDER BY store_id, material LIMIT ?",
        (limit,), fetch="all") or []


def upsert_inventory(store_id: str, material: str, stock: int, unit: str = "个", reorder_point: int = 0) -> None:
    if _backend == "mysql":
        _execute(
            "INSERT INTO inventory (store_id, material, stock, unit, reorder_point) VALUES (%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE stock=%s, unit=%s, reorder_point=%s",
            (store_id, material, stock, unit, reorder_point, stock, unit, reorder_point))
    else:
        existing = get_inventory(store_id, material)
        if existing:
            _execute("UPDATE inventory SET stock=?, unit=?, reorder_point=? WHERE store_id=? AND material=?",
                     (stock, unit, reorder_point, store_id, material))
        else:
            _execute("INSERT INTO inventory (store_id, material, stock, unit, reorder_point) VALUES (?,?,?,?,?)",
                     (store_id, material, stock, unit, reorder_point))


def update_inventory_stock(store_id: str, material: str, delta: int) -> Optional[dict]:
    """库存增减（delta 正为入库，负为出库），返回更新后记录。"""
    record = get_inventory(store_id, material)
    if not record:
        return None
    new_stock = max(0, int(record["stock"]) + delta)
    if _backend == "mysql":
        _execute("UPDATE inventory SET stock=%s WHERE store_id=%s AND material=%s",
                 (new_stock, store_id, material))
    else:
        _execute("UPDATE inventory SET stock=? WHERE store_id=? AND material=?",
                 (new_stock, store_id, material))
    return get_inventory(store_id, material)


# ---------------- promotions 促销政策 ----------------
def get_promotion(promo_code: str) -> Optional[dict]:
    return _execute(
        "SELECT * FROM promotions WHERE promo_code=%s" if _backend == "mysql"
        else "SELECT * FROM promotions WHERE promo_code=?",
        (promo_code,), fetch="one")


def list_promotions(status: Optional[str] = None, limit: int = 50) -> list:
    if status:
        return _execute(
            "SELECT * FROM promotions WHERE status=%s ORDER BY valid_until DESC LIMIT %s" if _backend == "mysql"
            else "SELECT * FROM promotions WHERE status=? ORDER BY valid_until DESC LIMIT ?",
            (status, limit), fetch="all") or []
    return _execute(
        "SELECT * FROM promotions ORDER BY valid_until DESC LIMIT %s" if _backend == "mysql"
        else "SELECT * FROM promotions ORDER BY valid_until DESC LIMIT ?",
        (limit,), fetch="all") or []


def upsert_promotion(promo_code: str, name: str, rule: str, status: str = "生效中",
                     valid_from: str = "", valid_until: str = "") -> None:
    if _backend == "mysql":
        _execute(
            "INSERT INTO promotions (promo_code, name, rule, status, valid_from, valid_until) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE name=%s, rule=%s, status=%s, valid_from=%s, valid_until=%s",
            (promo_code, name, rule, status, valid_from, valid_until,
             name, rule, status, valid_from, valid_until))
    else:
        existing = get_promotion(promo_code)
        if existing:
            _execute("UPDATE promotions SET name=?, rule=?, status=?, valid_from=?, valid_until=? WHERE promo_code=?",
                     (name, rule, status, valid_from, valid_until, promo_code))
        else:
            _execute("INSERT INTO promotions (promo_code, name, rule, status, valid_from, valid_until) VALUES (?,?,?,?,?,?)",
                     (promo_code, name, rule, status, valid_from, valid_until))


# ---------------- stores 门店主数据 ----------------
def get_store(store_id: str) -> Optional[dict]:
    return _execute(
        "SELECT * FROM stores WHERE store_id=%s" if _backend == "mysql"
        else "SELECT * FROM stores WHERE store_id=?",
        (store_id,), fetch="one")


def list_stores(status: Optional[str] = None, limit: int = 200) -> list:
    if status:
        return _execute(
            "SELECT * FROM stores WHERE status=%s ORDER BY store_id LIMIT %s" if _backend == "mysql"
            else "SELECT * FROM stores WHERE status=? ORDER BY store_id LIMIT ?",
            (status, limit), fetch="all") or []
    return _execute(
        "SELECT * FROM stores ORDER BY store_id LIMIT %s" if _backend == "mysql"
        else "SELECT * FROM stores ORDER BY store_id LIMIT ?",
        (limit,), fetch="all") or []


def upsert_store(store_id: str, name: str = "", address: str = "", phone: str = "",
                 manager: str = "", status: str = "营业中") -> None:
    if _backend == "mysql":
        _execute(
            "INSERT INTO stores (store_id, name, address, phone, manager, status) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE name=%s, address=%s, phone=%s, manager=%s, status=%s",
            (store_id, name, address, phone, manager, status,
             name, address, phone, manager, status))
    else:
        existing = get_store(store_id)
        if existing:
            _execute("UPDATE stores SET name=?, address=?, phone=?, manager=?, status=? WHERE store_id=?",
                     (name, address, phone, manager, status, store_id))
        else:
            _execute("INSERT INTO stores (store_id, name, address, phone, manager, status) VALUES (?,?,?,?,?,?)",
                     (store_id, name, address, phone, manager, status))


# ---------------- devices 设备清单 ----------------
def get_device(device_id: str) -> Optional[dict]:
    return _execute(
        "SELECT * FROM devices WHERE device_id=%s" if _backend == "mysql"
        else "SELECT * FROM devices WHERE device_id=?",
        (device_id,), fetch="one")


def list_devices(store_id: Optional[str] = None, limit: int = 100) -> list:
    if store_id:
        return _execute(
            "SELECT * FROM devices WHERE store_id=%s ORDER BY device_type LIMIT %s" if _backend == "mysql"
            else "SELECT * FROM devices WHERE store_id=? ORDER BY device_type LIMIT ?",
            (store_id, limit), fetch="all") or []
    return _execute(
        "SELECT * FROM devices ORDER BY store_id, device_type LIMIT %s" if _backend == "mysql"
        else "SELECT * FROM devices ORDER BY store_id, device_type LIMIT ?",
        (limit,), fetch="all") or []


def upsert_device(device_id: str, store_id: str, device_type: str, brand: str = "",
                  model: str = "", purchase_date: str = "", warranty_until: str = "",
                  status: str = "正常") -> None:
    if _backend == "mysql":
        _execute(
            "INSERT INTO devices (device_id, store_id, device_type, brand, model, purchase_date, warranty_until, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE store_id=%s, device_type=%s, brand=%s, model=%s, "
            "purchase_date=%s, warranty_until=%s, status=%s",
            (device_id, store_id, device_type, brand, model, purchase_date, warranty_until, status,
             store_id, device_type, brand, model, purchase_date, warranty_until, status))
    else:
        existing = get_device(device_id)
        if existing:
            _execute("UPDATE devices SET store_id=?, device_type=?, brand=?, model=?, purchase_date=?, warranty_until=?, status=? WHERE device_id=?",
                     (store_id, device_type, brand, model, purchase_date, warranty_until, status, device_id))
        else:
            _execute("INSERT INTO devices (device_id, store_id, device_type, brand, model, purchase_date, warranty_until, status) VALUES (?,?,?,?,?,?,?,?)",
                     (device_id, store_id, device_type, brand, model, purchase_date, warranty_until, status))


# ---------------- staff 员工信息 ----------------
def get_staff(staff_id: str) -> Optional[dict]:
    return _execute(
        "SELECT * FROM staff WHERE staff_id=%s" if _backend == "mysql"
        else "SELECT * FROM staff WHERE staff_id=?",
        (staff_id,), fetch="one")


def list_staff(role: Optional[str] = None, store_id: Optional[str] = None, limit: int = 100) -> list:
    sql = "SELECT * FROM staff WHERE 1=1"
    params = []
    if role:
        sql += " AND role=%s" if _backend == "mysql" else " AND role=?"
        params.append(role)
    if store_id:
        sql += " AND store_id=%s" if _backend == "mysql" else " AND store_id=?"
        params.append(store_id)
    sql += " ORDER BY name LIMIT %s" if _backend == "mysql" else " ORDER BY name LIMIT ?"
    params.append(limit)
    return _execute(sql, tuple(params), fetch="all") or []


def upsert_staff(staff_id: str, name: str, role: str = "店员", phone: str = "",
                 store_id: str = "", status: str = "在职") -> None:
    if _backend == "mysql":
        _execute(
            "INSERT INTO staff (staff_id, name, role, phone, store_id, status) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE name=%s, role=%s, phone=%s, store_id=%s, status=%s",
            (staff_id, name, role, phone, store_id, status,
             name, role, phone, store_id, status))
    else:
        existing = get_staff(staff_id)
        if existing:
            _execute("UPDATE staff SET name=?, role=?, phone=?, store_id=?, status=? WHERE staff_id=?",
                     (name, role, phone, store_id, status, staff_id))
        else:
            _execute("INSERT INTO staff (staff_id, name, role, phone, store_id, status) VALUES (?,?,?,?,?,?)",
                     (staff_id, name, role, phone, store_id, status))
