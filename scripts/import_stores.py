"""门店信息 Excel/CSV 批量导入脚本。

用法：
    python scripts/import_stores.py data/templates/stores.xlsx
    python scripts/import_stores.py data/templates/stores.csv

Excel/CSV 列名（支持中英文）：
    store_id | 门店编号 | 门店编码 | 编号
    name     | 门店名称 | 名称 | 店名
    address  | 地址 | 门店地址
    phone    | 电话 | 联系电话 | 门店电话
    manager  | 店长 | 负责人 | 店长姓名
    status   | 状态 | 营业状态（营业中/停业）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.db import init_db, upsert_store, list_stores


def _detect_columns(df: pd.DataFrame) -> dict:
    """自动识别中英文列名。"""
    col_map = {}
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl in ("store_id", "门店编号", "门店编码", "编号", "编码"):
            col_map["store_id"] = col
        elif cl in ("name", "门店名称", "名称", "店名"):
            col_map["name"] = col
        elif cl in ("address", "地址", "门店地址"):
            col_map["address"] = col
        elif cl in ("phone", "电话", "联系电话", "门店电话"):
            col_map["phone"] = col
        elif cl in ("manager", "店长", "负责人", "店长姓名"):
            col_map["manager"] = col
        elif cl in ("status", "状态", "营业状态"):
            col_map["status"] = col
    return col_map


def import_stores(file_path: str) -> int:
    """从 Excel/CSV 批量导入门店信息。"""
    path = Path(file_path)
    if not path.exists():
        print(f"[错误] 文件不存在：{file_path}")
        return 0

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    col_map = _detect_columns(df)
    if "store_id" not in col_map:
        print("[错误] 未找到门店编号列（store_id / 门店编号 / 编号）")
        print(f"当前列名：{list(df.columns)}")
        return 0

    total = 0
    for _, row in df.iterrows():
        store_id = str(row.get(col_map["store_id"], "")).strip()
        if not store_id or store_id.lower() == "nan":
            continue
        name = str(row.get(col_map.get("name", "name"), "")).strip()
        address = str(row.get(col_map.get("address", "address"), "")).strip()
        phone = str(row.get(col_map.get("phone", "phone"), "")).strip()
        manager = str(row.get(col_map.get("manager", "manager"), "")).strip()
        status = str(row.get(col_map.get("status", "status"), "营业中")).strip() or "营业中"
        # 清理 nan
        name = "" if name.lower() == "nan" else name
        address = "" if address.lower() == "nan" else address
        phone = "" if phone.lower() == "nan" else phone
        manager = "" if manager.lower() == "nan" else manager
        status = "营业中" if status.lower() == "nan" else status

        upsert_store(store_id, name, address, phone, manager, status)
        total += 1

    print(f"[门店导入] 完成：从 {path.name} 导入 {total} 家门店")
    return total


def list_stores_cmd():
    """查看本地已有的门店。"""
    stores = list_stores(limit=500)
    print(f"本地共 {len(stores)} 家门店：")
    for s in stores:
        print(f"  {s['store_id']} | {s['name']} | {s['status']} | {s.get('address', '')}")


if __name__ == "__main__":
    init_db()
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        list_stores_cmd()
    elif len(sys.argv) >= 2:
        import_stores(sys.argv[1])
    else:
        print("用法：")
        print("  python scripts/import_stores.py <excel/csv文件路径>  # 导入门店")
        print("  python scripts/import_stores.py list                   # 查看已有门店")
        print("示例：")
        print("  python scripts/import_stores.py data/templates/stores.xlsx")
