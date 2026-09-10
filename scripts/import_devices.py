"""设备信息 Excel/CSV 批量导入脚本。

用法：
    python scripts/import_devices.py data/templates/devices.xlsx

Excel/CSV 列名（支持中英文）：
    device_id    | 设备编号 | 资产编号 | 设备编码
    store_id     | 门店编号 | 所属门店
    device_type  | 设备类型 | 设备类别 | 类型
    brand        | 品牌 | 品牌型号
    model        | 型号 | 规格型号
    purchase_date| 采购日期 | 购入日期
    warranty_until| 保修截止 | 保修到期
    status       | 状态 | 设备状态（正常/故障/报废）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.db import init_db, upsert_device, list_devices


def _detect_columns(df: pd.DataFrame) -> dict:
    col_map = {}
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl in ("device_id", "设备编号", "资产编号", "设备编码", "编号"):
            col_map["device_id"] = col
        elif cl in ("store_id", "门店编号", "所属门店", "门店"):
            col_map["store_id"] = col
        elif cl in ("device_type", "设备类型", "设备类别", "类型", "类别"):
            col_map["device_type"] = col
        elif cl in ("brand", "品牌", "品牌型号"):
            col_map["brand"] = col
        elif cl in ("model", "型号", "规格型号"):
            col_map["model"] = col
        elif cl in ("purchase_date", "采购日期", "购入日期"):
            col_map["purchase_date"] = col
        elif cl in ("warranty_until", "保修截止", "保修到期", "保修期至"):
            col_map["warranty_until"] = col
        elif cl in ("status", "状态", "设备状态"):
            col_map["status"] = col
    return col_map


def _clean(val: str, default: str = "") -> str:
    v = str(val).strip()
    return default if v.lower() == "nan" else v


def import_devices(file_path: str) -> int:
    path = Path(file_path)
    if not path.exists():
        print(f"[错误] 文件不存在：{file_path}")
        return 0

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    col_map = _detect_columns(df)
    required = ["device_id", "store_id", "device_type"]
    missing = [r for r in required if r not in col_map]
    if missing:
        print(f"[错误] 缺少必要列：{missing}")
        print(f"当前列名：{list(df.columns)}")
        return 0

    total = 0
    for _, row in df.iterrows():
        device_id = _clean(row.get(col_map["device_id"], ""))
        if not device_id:
            continue
        store_id = _clean(row.get(col_map["store_id"], ""))
        device_type = _clean(row.get(col_map["device_type"], ""))
        brand = _clean(row.get(col_map.get("brand", "brand"), ""))
        model = _clean(row.get(col_map.get("model", "model"), ""))
        purchase_date = _clean(row.get(col_map.get("purchase_date", "purchase_date"), ""))
        warranty_until = _clean(row.get(col_map.get("warranty_until", "warranty_until"), ""))
        status = _clean(row.get(col_map.get("status", "status"), ""), "正常")

        upsert_device(device_id, store_id, device_type, brand, model,
                      purchase_date, warranty_until, status)
        total += 1

    print(f"[设备导入] 完成：从 {path.name} 导入 {total} 台设备")
    return total


def list_devices_cmd():
    devices = list_devices(limit=500)
    print(f"本地共 {len(devices)} 台设备：")
    for d in devices:
        print(f"  {d['device_id']} | {d['store_id']} | {d['device_type']} | {d.get('brand','')} {d.get('model','')} | {d['status']}")


if __name__ == "__main__":
    init_db()
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        list_devices_cmd()
    elif len(sys.argv) >= 2:
        import_devices(sys.argv[1])
    else:
        print("用法：")
        print("  python scripts/import_devices.py <excel/csv文件路径>  # 导入设备")
        print("  python scripts/import_devices.py list                   # 查看已有设备")
        print("示例：")
        print("  python scripts/import_devices.py data/templates/devices.xlsx")
