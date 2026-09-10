"""员工信息 Excel/CSV 批量导入脚本。

用法：
    python scripts/import_staff.py data/templates/staff.xlsx

Excel/CSV 列名（支持中英文）：
    staff_id | 员工编号 | 工号 | 编号
    name     | 姓名 | 员工姓名
    role     | 角色 | 岗位 | 职位（店长/店员/维修工/区域经理）
    phone    | 电话 | 手机号 | 联系电话
    store_id | 门店编号 | 所属门店
    status   | 状态 | 在职状态（在职/离职）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.db import init_db, upsert_staff, list_staff


def _detect_columns(df: pd.DataFrame) -> dict:
    col_map = {}
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl in ("staff_id", "员工编号", "工号", "编号", "员工工号"):
            col_map["staff_id"] = col
        elif cl in ("name", "姓名", "员工姓名", "名字"):
            col_map["name"] = col
        elif cl in ("role", "角色", "岗位", "职位", "职务"):
            col_map["role"] = col
        elif cl in ("phone", "电话", "手机号", "联系电话", "手机"):
            col_map["phone"] = col
        elif cl in ("store_id", "门店编号", "所属门店", "门店"):
            col_map["store_id"] = col
        elif cl in ("status", "状态", "在职状态", "员工状态"):
            col_map["status"] = col
    return col_map


def _clean(val: str, default: str = "") -> str:
    v = str(val).strip()
    return default if v.lower() == "nan" else v


def import_staff(file_path: str) -> int:
    path = Path(file_path)
    if not path.exists():
        print(f"[错误] 文件不存在：{file_path}")
        return 0

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    col_map = _detect_columns(df)
    required = ["staff_id", "name"]
    missing = [r for r in required if r not in col_map]
    if missing:
        print(f"[错误] 缺少必要列：{missing}")
        print(f"当前列名：{list(df.columns)}")
        return 0

    total = 0
    for _, row in df.iterrows():
        staff_id = _clean(row.get(col_map["staff_id"], ""))
        if not staff_id:
            continue
        name = _clean(row.get(col_map["name"], ""))
        role = _clean(row.get(col_map.get("role", "role"), ""), "店员")
        phone = _clean(row.get(col_map.get("phone", "phone"), ""))
        store_id = _clean(row.get(col_map.get("store_id", "store_id"), ""))
        status = _clean(row.get(col_map.get("status", "status"), ""), "在职")

        upsert_staff(staff_id, name, role, phone, store_id, status)
        total += 1

    print(f"[员工导入] 完成：从 {path.name} 导入 {total} 名员工")
    return total


def list_staff_cmd():
    staff = list_staff(limit=500)
    print(f"本地共 {len(staff)} 名员工：")
    for s in staff:
        print(f"  {s['staff_id']} | {s['name']} | {s['role']} | {s.get('store_id','')} | {s['status']}")


if __name__ == "__main__":
    init_db()
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        list_staff_cmd()
    elif len(sys.argv) >= 2:
        import_staff(sys.argv[1])
    else:
        print("用法：")
        print("  python scripts/import_staff.py <excel/csv文件路径>  # 导入员工")
        print("  python scripts/import_staff.py list                   # 查看已有员工")
        print("示例：")
        print("  python scripts/import_staff.py data/templates/staff.xlsx")
