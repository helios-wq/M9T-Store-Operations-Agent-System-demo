"""查询重写：同义词扩展（离线规则）+ 可选 LLM 改写（在线）。

同义词扩展用于关键词检索路：把口语化说法映射到文档里的标准词，
例如「报修 / 维修 / 坏了 / 故障」→ 归一到「设备报修」相关词集。
"""
from __future__ import annotations

from typing import List

from ..llm.client import llm_client

# 门店运营领域同义词表：口语 → 标准词集
SYNONYM_MAP: dict = {
    "坏了": ["故障", "损坏", "维修", "报修"],
    "故障": ["坏了", "损坏", "维修", "报修"],
    "维修": ["报修", "故障", "修理"],
    "报修": ["维修", "故障", "修理"],
    "修": ["报修", "维修"],
    "库存": ["物料", "存货", "还有多少", "余量", "数量"],
    "物料": ["库存", "存货", "余量"],
    "存货": ["库存", "物料"],
    "还有多少": ["库存", "余量", "数量"],
    "促销": ["活动", "优惠", "折扣", "政策"],
    "活动": ["促销", "优惠", "折扣"],
    "优惠": ["促销", "活动", "折扣"],
    "折扣": ["促销", "活动", "优惠"],
    "营业": ["开业", "开门", "闭店", "打烊"],
    "开业": ["营业", "开门"],
    "打烊": ["闭店", "营业"],
    "排班": ["值班", "班次"],
    "会员": ["积分", "储值"],
    "卫生": ["清洁", "消毒", "检查"],
    "sop": ["流程", "操作", "手册", "步骤"],
    "流程": ["sop", "操作", "步骤"],
    "设备": ["机器", "收银机", "冰箱", "空调", "烤箱"],
}


def expand_query(query: str) -> List[str]:
    """返回查询 + 扩展词列表（去重，保留原词）。"""
    terms = [query]
    for k, vals in SYNONYM_MAP.items():
        if k in query:
            terms.extend(vals)
    # 去重保序
    seen, out = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def llm_rewrite(query: str) -> str:
    """在线模式：让 LLM 把口语问题改写成检索友好的标准表达。"""
    if llm_client.offline:
        return query
    messages = [
        {"role": "system", "content": "你是检索查询改写器。把店长的口语化问题改写为适合知识库检索的简洁标准表述，只输出改写结果。"},
        {"role": "user", "content": query},
    ]
    try:
        return (llm_client.chat(messages, temperature=0.1) or query).strip()
    except Exception:
        return query


def rewrite_query(query: str) -> str:
    """对外主入口：扩展后的查询串（在线时叠加 LLM 改写结果）。"""
    expanded = " ".join(expand_query(query))
    if not llm_client.offline:
        rewritten = llm_rewrite(query)
        if rewritten and rewritten != query:
            expanded = f"{rewritten} {expanded}"
    return expanded
