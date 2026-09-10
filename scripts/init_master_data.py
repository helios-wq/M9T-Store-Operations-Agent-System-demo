"""主数据初始化脚本：把硬编码的库存/促销/门店/设备/员工数据写入数据库。

用法：
    python scripts/init_master_data.py          # 初始化全部主数据
    python scripts/init_master_data.py --force  # 强制覆盖已有数据

生产环境应通过 ERP/营销系统同步，本脚本用于零配置演示和首次部署。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.tools import INVENTORY, PROMOTIONS, STORE_IDS, DEVICE_TYPES
from app.db import (
    init_db, upsert_inventory, upsert_promotion, upsert_store,
    upsert_device, upsert_staff, list_inventory, list_promotions, list_stores,
)


def init_inventory(force: bool = False) -> int:
    """初始化物料库存（给 S001-S005 各门店初始化演示数据）。"""
    existing = list_inventory(limit=1)
    if existing and not force:
        print(f"[库存] 已有 {len(existing)} 条数据，跳过（用 --force 覆盖）")
        return 0
    count = 0
    for store_idx in range(1, 6):
        store_id = f"S{store_idx:03d}"
        for material, info in INVENTORY.items():
            # 不同门店库存做小幅度浮动，模拟真实数据
            seed = store_idx * 7 + sum(ord(c) for c in material)
            stock = max(0, info["stock"] + (seed % 5 - 2) * 50)
            upsert_inventory(store_id, material, stock, info["unit"], info["reorder"])
            count += 1
    print(f"[库存] 初始化完成：{count} 条（S001-S005 × {len(INVENTORY)} 种物料）")
    return count


def init_promotions(force: bool = False) -> int:
    """初始化促销政策。"""
    existing = list_promotions(limit=1)
    if existing and not force:
        print(f"[促销] 已有 {len(existing)} 条数据，跳过（用 --force 覆盖）")
        return 0
    count = 0
    for code, p in PROMOTIONS.items():
        upsert_promotion(code, p["name"], p["rule"], p["status"], "", p["valid_until"])
        count += 1
    print(f"[促销] 初始化完成：{count} 条政策")
    return count


def init_stores(force: bool = False) -> int:
    """初始化门店主数据（S001-S010 演示门店）。"""
    existing = list_stores(limit=1)
    if existing and not force:
        print(f"[门店] 已有 {len(existing)} 条数据，跳过（用 --force 覆盖）")
        return 0
    count = 0
    for i in range(1, 11):
        sid = f"S{i:03d}"
        upsert_store(
            sid, f"{sid} 直营门店", f"上海市演示区路{i}号",
            f"021-0000{i:04d}", f"店长{i}", "营业中",
        )
        count += 1
    print(f"[门店] 初始化完成：{count} 家门店（S001-S010）")
    return count


def init_devices(force: bool = False) -> int:
    """初始化设备清单（S001 门店每种设备各一台）。"""
    count = 0
    for i, dtype in enumerate(DEVICE_TYPES, start=1):
        device_id = f"D{i:04d}"
        upsert_device(
            device_id, "S001", dtype, f"品牌{i}", f"型号-{dtype}",
            "2025-01-15", "2028-01-14", "正常",
        )
        count += 1
    print(f"[设备] 初始化完成：{count} 台设备（S001 门店）")
    return count


def init_staff(force: bool = False) -> int:
    """初始化员工信息（演示数据）。"""
    staff_list = [
        ("E001", "张三", "店长", "13800000001", "S001", "在职"),
        ("E002", "李四", "店员", "13800000002", "S001", "在职"),
        ("E003", "王五", "维修工", "13800000003", "S001", "在职"),
        ("E004", "赵六", "区域经理", "13800000004", "S001", "在职"),
    ]
    count = 0
    for sid, name, role, phone, store, status in staff_list:
        upsert_staff(sid, name, role, phone, store, status)
        count += 1
    print(f"[员工] 初始化完成：{count} 名员工")
    return count


def main():
    parser = argparse.ArgumentParser(description="主数据初始化脚本")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有数据")
    args = parser.parse_args()

    print("=" * 60)
    print("门店运营智能助手 - 主数据初始化")
    print("=" * 60)

    init_db()
    total = 0
    total += init_inventory(args.force)
    total += init_promotions(args.force)
    total += init_stores(args.force)
    total += init_devices(args.force)
    total += init_staff(args.force)

    print("=" * 60)
    print(f"全部完成，共初始化 {total} 条主数据")
    print("=" * 60)


if __name__ == "__main__":
    main()
