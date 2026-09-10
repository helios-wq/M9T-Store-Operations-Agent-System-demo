"""库存同步脚本：模拟从 ERP/POS 系统拉取最新库存并更新到数据库。

生产环境应替换为真实的 ERP API 调用，本脚本提供：
1. 模拟同步（随机波动，用于演示和测试）
2. CSV/Excel 批量导入（从 POS 系统导出的库存表导入）
3. 单物料手动更新（用于调试）
4. 库存增减（出库/入库）

用法：
    python scripts/sync_inventory.py                          # 模拟全量同步（随机波动）
    python scripts/sync_inventory.py --store S001             # 只同步指定门店
    python scripts/sync_inventory.py --import data/templates/inventory.csv  # 从 CSV 批量导入
    python scripts/sync_inventory.py --set S001 可乐杯 500    # 手动设置某物料库存
    python scripts/sync_inventory.py --delta S001 可乐杯 -100 # 库存增减（出库/入库）

CSV/Excel 列名（支持中英文）：
    store_id     | 门店编号 | 门店
    material     | 物料名称 | 物料 | 商品名称
    stock        | 库存数量 | 库存 | 数量
    unit         | 单位 | 计量单位
    reorder_point| 补货线 | 安全库存 | 补货阈值
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.db import init_db, list_inventory, upsert_inventory, get_inventory, update_inventory_stock


def simulate_sync(store_id: str = None, volatility: int = 20) -> int:
    """模拟 ERP 同步：对现有库存做小幅度随机波动。

    生产环境替换为：
        response = requests.get("https://erp.example.com/api/inventory", headers=...)
        for item in response.json():
            upsert_inventory(item["store_id"], item["material"], item["stock"], ...)
    """
    items = list_inventory(store_id=store_id, limit=500)
    if not items:
        print("[同步] 数据库中暂无库存数据，请先运行 init_master_data.py")
        return 0
    count = 0
    for item in items:
        current = int(item["stock"])
        # 模拟 ERP 返回的最新库存（在当前值基础上 ±volatility% 波动）
        delta_pct = random.uniform(-volatility / 100, volatility / 100)
        new_stock = max(0, int(current * (1 + delta_pct)))
        upsert_inventory(
            item["store_id"], item["material"], new_stock,
            item.get("unit", "个"), int(item.get("reorder_point", 0)),
        )
        count += 1
    store_msg = f"门店 {store_id}" if store_id else "全部门店"
    print(f"[同步] {store_msg} 模拟同步完成：更新 {count} 条库存记录")
    return count


def set_inventory(store_id: str, material: str, stock: int) -> None:
    """手动设置某物料库存（用于调试和手动修正）。"""
    existing = get_inventory(store_id, material)
    unit = existing["unit"] if existing else "个"
    reorder = int(existing["reorder_point"]) if existing else 0
    upsert_inventory(store_id, material, stock, unit, reorder)
    print(f"[设置] {store_id} {material} 库存已设置为 {stock} {unit}")


def delta_inventory(store_id: str, material: str, delta: int) -> None:
    """库存增减（delta 正为入库，负为出库）。"""
    result = update_inventory_stock(store_id, material, delta)
    if result:
        action = "入库" if delta > 0 else "出库"
        print(f"[增减] {store_id} {material} {action} {abs(delta)}，当前库存：{result['stock']} {result.get('unit', '个')}")
    else:
        print(f"[增减] 未找到 {store_id} {material}，请先初始化主数据")


def _detect_inventory_columns(df: pd.DataFrame) -> dict:
    """自动识别中英文列名。"""
    col_map = {}
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl in ("store_id", "门店编号", "门店", "所属门店"):
            col_map["store_id"] = col
        elif cl in ("material", "物料名称", "物料", "商品名称", "品名", "商品"):
            col_map["material"] = col
        elif cl in ("stock", "库存数量", "库存", "数量", "现有库存", "可用库存"):
            col_map["stock"] = col
        elif cl in ("unit", "单位", "计量单位"):
            col_map["unit"] = col
        elif cl in ("reorder_point", "补货线", "安全库存", "补货阈值", "最低库存"):
            col_map["reorder_point"] = col
    return col_map


def _clean(val: str, default: str = "") -> str:
    v = str(val).strip()
    return default if v.lower() == "nan" else v


def import_from_csv(file_path: str) -> int:
    """从 CSV/Excel 批量导入库存（POS 系统导出的库存表）。"""
    path = Path(file_path)
    if not path.exists():
        print(f"[错误] 文件不存在：{file_path}")
        return 0

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    col_map = _detect_inventory_columns(df)
    required = ["store_id", "material", "stock"]
    missing = [r for r in required if r not in col_map]
    if missing:
        print(f"[错误] 缺少必要列：{missing}")
        print(f"当前列名：{list(df.columns)}")
        return 0

    total = 0
    for _, row in df.iterrows():
        store_id = _clean(row.get(col_map["store_id"], ""))
        material = _clean(row.get(col_map["material"], ""))
        stock_str = _clean(row.get(col_map["stock"], ""), "0")
        if not store_id or not material:
            continue
        try:
            stock = max(0, int(float(stock_str)))
        except (ValueError, TypeError):
            stock = 0
        unit = _clean(row.get(col_map.get("unit", "unit"), ""), "个")
        reorder_str = _clean(row.get(col_map.get("reorder_point", "reorder_point"), ""), "0")
        try:
            reorder_point = max(0, int(float(reorder_str)))
        except (ValueError, TypeError):
            reorder_point = 0

        upsert_inventory(store_id, material, stock, unit, reorder_point)
        total += 1

    print(f"[CSV导入] 完成：从 {path.name} 导入 {total} 条库存记录")
    return total


def main():
    parser = argparse.ArgumentParser(description="库存同步脚本（模拟 ERP/POS 同步）")
    parser.add_argument("--store", help="只同步指定门店（如 S001）")
    parser.add_argument("--import", dest="import_file", help="从 CSV/Excel 批量导入库存")
    parser.add_argument("--set", nargs=3, metavar=("STORE", "MATERIAL", "STOCK"),
                        help="手动设置库存：门店 物料 数量")
    parser.add_argument("--delta", nargs=3, metavar=("STORE", "MATERIAL", "DELTA"),
                        help="库存增减：门店 物料 增减量（正为入库，负为出库）")
    parser.add_argument("--volatility", type=int, default=20, help="模拟同步波动百分比（默认 20%%）")
    args = parser.parse_args()

    init_db()

    if args.import_file:
        import_from_csv(args.import_file)
    elif args.set:
        store, material, stock = args.set
        set_inventory(store, material, int(stock))
    elif args.delta:
        store, material, delta = args.delta
        delta_inventory(store, material, int(delta))
    else:
        simulate_sync(args.store, args.volatility)


if __name__ == "__main__":
    main()
