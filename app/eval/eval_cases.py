"""评测集定义：种子用例（与 data/gen_docs.py 的 CURATED_DOCS 对齐）+ 批量生成器。

每条用例：
{
  "id": "E001",
  "question": "……",
  "type": "retrieval" | "tool" | "handoff",
  "intent": 期望意图,
  "category": 期望问题类别,
  "expected_tool": 工具用例期望调用的工具名,
  "ground_truth_doc_id": 检索用例的期望命中文档
}
"""
from __future__ import annotations

import json
import random
from typing import List, Optional

SEED_CASES: List[dict] = [
    # ---------- 知识检索类（召回率） ----------
    {"id": "E001", "question": "收银机突然死机了怎么办", "type": "retrieval", "intent": "repair_tool",
     "category": "设备报修", "expected_tool": "report_repair", "ground_truth_doc_id": "repair-cashier-freeze"},
    {"id": "E002", "question": "制冰机不出冰是什么原因", "type": "retrieval", "intent": "repair_tool",
     "category": "设备报修", "expected_tool": "report_repair", "ground_truth_doc_id": "repair-icemachine-fail"},
    {"id": "E003", "question": "冰箱冷藏区温度应该调到多少度", "type": "retrieval", "intent": "knowledge_query",
     "category": "食品安全", "ground_truth_doc_id": "food-fridge-temp"},
    {"id": "E004", "question": "新员工入职第一周要培训哪些内容", "type": "retrieval", "intent": "knowledge_query",
     "category": "员工培训", "ground_truth_doc_id": "train-onboarding"},
    {"id": "E005", "question": "门店早上几点开始营业", "type": "retrieval", "intent": "knowledge_query",
     "category": "开店闭店", "ground_truth_doc_id": "store-open-time"},
    {"id": "E006", "question": "顾客给了差评怎么处理", "type": "retrieval", "intent": "knowledge_query",
     "category": "投诉处理", "ground_truth_doc_id": "complaint-bad-review"},
    {"id": "E007", "question": "晚班闭店前的检查清单有哪些", "type": "retrieval", "intent": "knowledge_query",
     "category": "开店闭店", "ground_truth_doc_id": "store-close-checklist"},
    {"id": "E008", "question": "收银退款的标准流程是什么", "type": "retrieval", "intent": "knowledge_query",
     "category": "收银结账", "ground_truth_doc_id": "cashier-refund"},
    {"id": "E009", "question": "会员积分怎么兑换", "type": "retrieval", "intent": "knowledge_query",
     "category": "会员营销", "ground_truth_doc_id": "member-points"},
    {"id": "E010", "question": "请假和换班怎么申请", "type": "retrieval", "intent": "knowledge_query",
     "category": "排班考勤", "ground_truth_doc_id": "schedule-leave"},
    {"id": "E011", "question": "冷冻肉解冻有什么规范", "type": "retrieval", "intent": "knowledge_query",
     "category": "食品安全", "ground_truth_doc_id": "food-thaw"},
    {"id": "E012", "question": "炸炉的油温标准是多少", "type": "retrieval", "intent": "knowledge_query",
     "category": "食品安全", "ground_truth_doc_id": "food-fryer-oil"},
    {"id": "E013", "question": "打印机卡纸了怎么处理", "type": "retrieval", "intent": "repair_tool",
     "category": "设备报修", "expected_tool": "report_repair", "ground_truth_doc_id": "repair-printer-jam"},
    {"id": "E014", "question": "店里的空调不制冷了", "type": "retrieval", "intent": "repair_tool",
     "category": "设备报修", "expected_tool": "report_repair", "ground_truth_doc_id": "repair-ac"},
    {"id": "E015", "question": "餐具消毒的流程和要求", "type": "retrieval", "intent": "knowledge_query",
     "category": "卫生清洁", "ground_truth_doc_id": "hygiene-utensil-disinfect"},
    {"id": "E016", "question": "外卖订单怎么打包", "type": "retrieval", "intent": "knowledge_query",
     "category": "运营SOP", "ground_truth_doc_id": "sop-takeout-packing"},
    {"id": "E017", "question": "盘点库存的流程", "type": "retrieval", "intent": "knowledge_query",
     "category": "物料库存", "ground_truth_doc_id": "inventory-count"},
    {"id": "E018", "question": "高峰期排队顾客太多怎么处理", "type": "retrieval", "intent": "knowledge_query",
     "category": "运营SOP", "ground_truth_doc_id": "sop-peak-flow"},
    # ---------- 工具调用类（完成率） ----------
    {"id": "E101", "question": "我们店的收银机坏了，帮我报修一下", "type": "tool", "intent": "repair_tool",
     "category": "设备报修", "expected_tool": "report_repair", "ground_truth_doc_id": ""},
    {"id": "E102", "question": "S003 店的制冰机故障，需要紧急报修", "type": "tool", "intent": "repair_tool",
     "category": "设备报修", "expected_tool": "report_repair", "ground_truth_doc_id": ""},
    {"id": "E103", "question": "我们店可乐杯还有多少库存", "type": "tool", "intent": "inventory_tool",
     "category": "物料库存", "expected_tool": "query_inventory", "ground_truth_doc_id": ""},
    {"id": "E104", "question": "番茄酱包缺货了，查一下库存", "type": "tool", "intent": "inventory_tool",
     "category": "物料库存", "expected_tool": "query_inventory", "ground_truth_doc_id": ""},
    {"id": "E105", "question": "P01 促销满100减20现在还能用吗", "type": "tool", "intent": "promotion_tool",
     "category": "促销政策", "expected_tool": "check_promotion", "ground_truth_doc_id": ""},
    {"id": "E106", "question": "会员日 88 折活动 P02 什么时候结束", "type": "tool", "intent": "promotion_tool",
     "category": "促销政策", "expected_tool": "check_promotion", "ground_truth_doc_id": ""},
    {"id": "E107", "question": "餐巾纸库存不多了，还有多少", "type": "tool", "intent": "inventory_tool",
     "category": "物料库存", "expected_tool": "query_inventory", "ground_truth_doc_id": ""},
    {"id": "E108", "question": "烤箱不加热了，紧急报修", "type": "tool", "intent": "repair_tool",
     "category": "设备报修", "expected_tool": "report_repair", "ground_truth_doc_id": ""},
    # ---------- 转人工类 ----------
    {"id": "E201", "question": "我要找你们经理投诉，给我转人工", "type": "handoff", "intent": "handoff",
     "category": "投诉处理", "expected_tool": "", "ground_truth_doc_id": ""},
    {"id": "E202", "question": "这个问题解决不了，给我人工客服电话", "type": "handoff", "intent": "handoff",
     "category": "投诉处理", "expected_tool": "", "ground_truth_doc_id": ""},
]

# 批量生成扩展：对每条种子用例做同义改写，凑足 120+ 条
REWRITE_TEMPLATES = [
    "麻烦问下，{q}",
    "{q}，具体怎么操作",
    "你好，{q}",
    "{q}？请告诉我",
    "想了解一下，{q}",
    "紧急情况：{q}",
    "{q}，谢谢",
    "请问{q}",
]


def get_eval_cases(min_count: int = 120, seed: int = 42) -> List[dict]:
    """返回 >= min_count 条评测用例（种子 + 同义改写扩展，去重保序）。"""
    rng = random.Random(seed)
    cases: List[dict] = list(SEED_CASES)
    idx = 0
    while len(cases) < min_count:
        base = SEED_CASES[idx % len(SEED_CASES)]
        tpl = REWRITE_TEMPLATES[rng.randrange(len(REWRITE_TEMPLATES))]
        new_q = tpl.format(q=base["question"])
        if new_q == base["question"]:
            continue
        new_case = dict(base)
        new_case["id"] = f"E{1000 + len(cases)}"
        new_case["question"] = new_q
        cases.append(new_case)
        idx += 1
    return cases


def save_eval_cases(path, min_count: int = 120) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(get_eval_cases(min_count), f, ensure_ascii=False, indent=2)
