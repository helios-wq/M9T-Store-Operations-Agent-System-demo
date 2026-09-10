"""促销活动自动过期检查脚本。

每天凌晨运行，检查所有生效中的促销活动，如果 valid_until 已过期，
自动将状态改为「已过期」。

用法：
    python scripts/check_promotions.py          # 检查并自动过期
    python scripts/check_promotions.py --dry-run # 只检查不修改（预览）
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import init_db, list_promotions, upsert_promotion


def check_expired(dry_run: bool = False) -> int:
    """检查生效中的促销活动，过期的自动标记为已过期。"""
    today = datetime.now().strftime("%Y-%m-%d")
    active = list_promotions(status="生效中", limit=500)

    expired_count = 0
    for p in active:
        valid_until = p.get("valid_until", "")
        if not valid_until:
            continue
        # 比较日期（支持 YYYY-MM-DD 格式）
        try:
            expire_date = datetime.strptime(valid_until[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        if expire_date < today:
            expired_count += 1
            print(f"[过期] {p['promo_code']} | {p['name']} | 截止 {valid_until}")
            if not dry_run:
                upsert_promotion(
                    p["promo_code"], p["name"], p["rule"], "已过期",
                    p.get("valid_from", ""), valid_until,
                )

    if dry_run:
        print(f"[预览] 共 {expired_count} 条活动已过期（未修改）")
    else:
        print(f"[完成] 共 {expired_count} 条活动已标记为过期")
    return expired_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="促销活动自动过期检查")
    parser.add_argument("--dry-run", action="store_true", help="只检查不修改")
    args = parser.parse_args()

    init_db()
    check_expired(dry_run=args.dry_run)
