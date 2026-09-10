"""促销政策 Excel/CSV 批量导入脚本。

用法：
    python scripts/import_promotions.py data/templates/promotions.xlsx

Excel/CSV 列名（支持中英文）：
    promo_code | 活动编号 | 促销编号 | 编号
    name       | 活动名称 | 促销名称 | 名称
    rule       | 活动规则 | 促销规则 | 规则 | 详情
    status     | 状态 | 活动状态（生效中/已过期/已停用）
    valid_from | 开始日期 | 生效日期 | 开始时间
    valid_until| 结束日期 | 截止日期 | 结束时间
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.db import init_db, upsert_promotion, list_promotions


def _detect_columns(df: pd.DataFrame) -> dict:
    col_map = {}
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl in ("promo_code", "活动编号", "促销编号", "编号", "编码"):
            col_map["promo_code"] = col
        elif cl in ("name", "活动名称", "促销名称", "名称", "活动名"):
            col_map["name"] = col
        elif cl in ("rule", "活动规则", "促销规则", "规则", "详情", "说明"):
            col_map["rule"] = col
        elif cl in ("status", "状态", "活动状态", "促销状态"):
            col_map["status"] = col
        elif cl in ("valid_from", "开始日期", "生效日期", "开始时间", "起始日期"):
            col_map["valid_from"] = col
        elif cl in ("valid_until", "结束日期", "截止日期", "结束时间", "到期日期"):
            col_map["valid_until"] = col
    return col_map


def _clean(val: str, default: str = "") -> str:
    v = str(val).strip()
    return default if v.lower() == "nan" else v


def import_promotions(file_path: str) -> int:
    path = Path(file_path)
    if not path.exists():
        print(f"[错误] 文件不存在：{file_path}")
        return 0

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    col_map = _detect_columns(df)
    required = ["promo_code", "name", "rule"]
    missing = [r for r in required if r not in col_map]
    if missing:
        print(f"[错误] 缺少必要列：{missing}")
        print(f"当前列名：{list(df.columns)}")
        return 0

    total = 0
    for _, row in df.iterrows():
        promo_code = _clean(row.get(col_map["promo_code"], ""))
        if not promo_code:
            continue
        name = _clean(row.get(col_map["name"], ""))
        rule = _clean(row.get(col_map["rule"], ""))
        status = _clean(row.get(col_map.get("status", "status"), ""), "生效中")
        valid_from = _clean(row.get(col_map.get("valid_from", "valid_from"), ""))
        valid_until = _clean(row.get(col_map.get("valid_until", "valid_until"), ""))

        upsert_promotion(promo_code, name, rule, status, valid_from, valid_until)
        total += 1

    print(f"[促销导入] 完成：从 {path.name} 导入 {total} 条促销政策")
    return total


def list_promotions_cmd():
    promos = list_promotions(limit=200)
    print(f"本地共 {len(promos)} 条促销政策：")
    for p in promos:
        print(f"  {p['promo_code']} | {p['name']} | {p['status']} | 至 {p.get('valid_until','')}")


if __name__ == "__main__":
    init_db()
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        list_promotions_cmd()
    elif len(sys.argv) >= 2:
        import_promotions(sys.argv[1])
    else:
        print("用法：")
        print("  python scripts/import_promotions.py <excel/csv文件路径>  # 导入促销")
        print("  python scripts/import_promotions.py list                   # 查看已有促销")
        print("示例：")
        print("  python scripts/import_promotions.py data/templates/promotions.xlsx")
