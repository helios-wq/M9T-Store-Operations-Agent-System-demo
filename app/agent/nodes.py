"""Agent 状态机 4 节点：意图识别 / 知识检索 / 工具执行 / 结果输出。

所有节点函数签名统一为 `node(state: dict) -> dict`（返回字段增量更新），
因此同一套节点既可以被 LangGraph 编排，也可以被 graph.py 中的
手动执行器逐个调用 —— 框架与业务逻辑解耦，是本项目可测试性的关键。
"""
from __future__ import annotations

import json
import re
from typing import Dict, List

from ..config import settings
from ..llm.client import llm_client
from ..rag.retriever import retriever as _retriever
from .tools import TOOL_CATEGORY_MAP, TOOL_FUNCTIONS, TOOL_INTENT_MAP, TOOL_SCHEMAS

# 问题类别白名单（对应 data/raw_docs 文档体系）
CATEGORIES = [
    "设备报修", "物料库存", "促销政策", "运营SOP", "食品安全",
    "排班考勤", "收银结账", "会员营销", "卫生清洁", "投诉处理", "开店闭店", "员工培训",
]

ALLOWED_INTENTS = {"repair_tool", "inventory_tool", "promotion_tool", "knowledge_query", "handoff", "chat"}

# ---------------- 离线规则（无 LLM Key 时保证全流程可跑） ----------------

_REPAIR_KW = ["报修", "维修", "坏了", "故障", "修", "不能用", "出问题", "损坏", "死机",
              "卡纸", "不制冷", "不出冰", "不加热", "黑屏", "不工作", "失灵", "漏电", "异响"]
_INVENTORY_KW = ["库存", "还有多少", "物料", "存货", "余量", "够不够", "还有没有", "缺货"]
_PROMOTION_KW = ["促销", "活动", "优惠", "折扣", "满减", "买一送一", "会员日", "P01", "P02", "P03", "P04"]
_HANDOFF_KW = ["人工", "投诉", "找经理", "电话", "转接", "负责人"]

_INTENT_KEYWORDS = [
    ("repair_tool", _REPAIR_KW),
    ("inventory_tool", _INVENTORY_KW),
    ("promotion_tool", _PROMOTION_KW),
    ("handoff", _HANDOFF_KW),
]

_CATEGORY_KEYWORDS = [
    ("设备报修", _REPAIR_KW + ["冰箱", "烤箱", "收银机", "空调", "炸炉", "制冰机", "设备"]),
    ("物料库存", _INVENTORY_KW + ["杯子", "袋子", "纸", "酱包", "吸管"]),
    ("促销政策", _PROMOTION_KW),
    ("食品安全", ["食品安全", "过期", "保质期", "储存温度", "解冻"]),
    ("卫生清洁", ["卫生", "清洁", "消毒", "打扫", "灭蝇"]),
    ("收银结账", ["收银", "结账", "退款", "找零", "pos", "刷卡"]),
    ("排班考勤", ["排班", "考勤", "请假", "换班", "值班"]),
    ("会员营销", ["会员", "积分", "储值", "办卡"]),
    ("投诉处理", ["投诉", "差评", "纠纷", "顾客不满"]),
    ("开店闭店", ["开店", "闭店", "开门", "打烊", "营业前", "营业后"]),
    ("员工培训", ["培训", "新员工", "带教"]),
    ("运营SOP", ["sop", "流程", "手册", "标准", "操作规范"]),
]


def _offline_intent(query: str) -> Dict:
    q = query.lower()
    for intent, kws in _INTENT_KEYWORDS:
        if any(k.lower() in q for k in kws):
            return {"intent": intent, "category": _match_category(query), "confidence": 0.9}
    return {"intent": "knowledge_query", "category": _match_category(query), "confidence": 0.7}


def _match_category(query: str) -> str:
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(k.lower() in query.lower() for k in kws):
            return cat
    return ""


# ---------------- 节点 1：意图识别 ----------------

INTENT_PROMPT = """你是门店助手的意图识别器。判断用户问题的意图并输出 JSON：
{"intent": "repair_tool|inventory_tool|promotion_tool|knowledge_query|handoff|chat",
 "category": "问题类别，从【设备报修, 物料库存, 促销政策, 运营SOP, 食品安全, 排班考勤, 收银结账, 会员营销, 卫生清洁, 投诉处理, 开店闭店, 员工培训】中选择",
 "confidence": 0到1的置信度}
- repair_tool：设备故障/报修；inventory_tool：查库存物料；promotion_tool：促销/优惠/折扣政策；
- knowledge_query：查询 SOP/流程/规范类知识；handoff：要转人工/投诉；chat：闲聊问候。
只输出 JSON。"""


def intent_node(state: Dict) -> Dict:
    query = state.get("query", "")
    messages = state.get("messages", [])
    if llm_client.offline:
        result = _offline_intent(query)
    else:
        result = llm_client.extract_json([
            {"role": "system", "content": INTENT_PROMPT},
            *messages[-4:],
        ])
        if result.get("intent") not in ALLOWED_INTENTS:
            result = _offline_intent(query)
        if not result.get("category"):
            result["category"] = _match_category(query)
    # 会话中意图切换：上一轮是工具流、本轮换了意图 → 清理工具中间状态
    update = {
        "intent": result["intent"],
        "category": result.get("category", ""),
        "confidence": float(result.get("confidence", 0.8)),
    }
    prev_intent = state.get("intent")
    if prev_intent and prev_intent.endswith("_tool") and update["intent"] != prev_intent:
        update["tool_calls"] = []
        update["tool_results"] = []
        update["needs_retrieval"] = False
    return update


# ---------------- 节点 2：知识检索 ----------------

def retrieve_node(state: Dict) -> Dict:
    query = state.get("query", "")
    category = state.get("category", "")
    rounds = state.get("retrieval_rounds", 0) + 1
    try:
        results = _retriever.retrieve(query, top_k=3, query_category=category)
        context = _retriever.build_context(results)
        return {
            "retrieval_results": [r.to_dict() for r in results],
            "context": context,
            "retrieval_rounds": rounds,
            "retry_retrieval": False,
        }
    except Exception as e:
        return {
            "retrieval_results": [], "context": "",
            "retrieval_rounds": rounds, "error": f"检索失败: {e}",
        }


# ---------------- 节点 3：工具执行（ReAct / Function Calling） ----------------

def _rule_pick_tool(intent: str, query: str, store_id: str) -> tuple:
    """离线工具选择与参数抽取。"""
    tool_name = TOOL_INTENT_MAP.get(intent)
    if not tool_name:
        return None, {}
    args = {"store_id": store_id}
    if tool_name == "report_repair":
        device = ""
        for d in ["收银机", "制冰机", "冷藏冰箱", "冷冻柜", "烤箱", "炸炉", "空调", "点餐屏", "打印机", "微波炉"]:
            if d in query:
                device = d
                break
        args["device"] = device or "设备"
        args["problem_desc"] = query
        if any(k in query for k in ["紧急", "马上", "立即"]):
            args["priority"] = "紧急"
    elif tool_name == "query_inventory":
        for m in ["可乐杯", "薯条袋", "汉堡纸", "番茄酱包", "餐巾纸", "冰激凌杯", "打包袋", "吸管"]:
            if m in query:
                args["material"] = m
                break
        args.setdefault("material", query)
    elif tool_name == "check_promotion":
        m = re.search(r"[Pp]\d{1,2}", query)
        args["policy_code"] = m.group(0).upper() if m else ""
    return tool_name, args


def _llm_pick_tool(messages: List[dict], query: str) -> tuple:
    """在线 Function Calling：让 LLM 自主选择工具与参数。"""
    resp = llm_client._client.chat.completions.create(
        model=settings.llm_model,
        messages=messages + [{"role": "user", "content": query}],
        tools=[{"type": "function", "function": s} for s in TOOL_SCHEMAS],
        tool_choice="auto",
        temperature=0.1,
    )
    choice = resp.choices[0].message
    if not choice.tool_calls:
        return None, {}
    tc = choice.tool_calls[0]
    name = tc.function.name
    args = json.loads(tc.function.arguments or "{}")
    return name, args


def tool_node(state: Dict) -> Dict:
    intent = state.get("intent", "")
    query = state.get("query", "")
    store_id = state.get("store_id", "S001")
    messages = state.get("messages", [])
    tool_calls: List[dict] = list(state.get("tool_calls", []))
    tool_results: List[dict] = list(state.get("tool_results", []))
    needs_retrieval = False
    error = None

    if llm_client.offline:
        name, args = _rule_pick_tool(intent, query, store_id)
    else:
        try:
            name, args = _llm_pick_tool(messages, query)
        except Exception:
            name, args = _rule_pick_tool(intent, query, store_id)
        if name is None:
            name, args = _rule_pick_tool(intent, query, store_id)

    if name is None:
        needs_retrieval = True
        error = "无法确定需要调用的工具"
    else:
        args.setdefault("store_id", store_id)
        tool_calls.append({"name": name, "arguments": args})
        try:
            fn = TOOL_FUNCTIONS[name]
            output = fn(**args)
            ok = output.get("ok", False)
            if not ok:
                error = output.get("error", "工具执行失败")
            tool_results.append({"name": name, "ok": ok, "output": output, "error": error})
            # 工具执行失败 → 降级：携带工具结果与错误，转知识检索兜底
            if not ok:
                needs_retrieval = True
        except Exception as e:
            error = f"工具异常: {e}"
            tool_results.append({"name": name, "ok": False, "output": {}, "error": error})
            needs_retrieval = True

    update = {"tool_calls": tool_calls, "tool_results": tool_results, "needs_retrieval": needs_retrieval}
    if error:
        update["error"] = error
    return update


# ---------------- 节点 4：结果输出 ----------------

OUTPUT_PROMPT = """你是连锁门店运营智能助手，服务对象是门店店长/店员。
请只依据给定的【检索上下文】和【工具结果】回答，不得编造知识库之外的内容；
若信息不足，明确说明并建议转人工。
回答要求：先给结论，再给关键步骤；引用来源时用 [来源1] 标注。"""


def _offline_answer(state: Dict) -> Dict:
    intent = state.get("intent")
    query = state.get("query", "")
    results = state.get("retrieval_results", [])
    tool_results = state.get("tool_results", [])
    handoff = intent == "handoff"

    if intent == "chat":
        return {"final_answer": "您好，我是门店运营智能助手，可以帮您查询运营SOP、报修设备、核对促销政策或物料库存，请问需要什么帮助？",
                "citations": [], "handoff": False}

    if intent.endswith("_tool") and tool_results:
        last = tool_results[-1]
        if last.get("ok"):
            out = last["output"]
            if last["name"] == "report_repair":
                answer = (f"报修工单已受理：单号 {out['order_no']}，设备「{out['device']}」，"
                          f"优先级：{out['priority']}，{out['sla']}。维修师傅将尽快联系门店。")
            elif last["name"] == "query_inventory":
                answer = (f"门店 {out['store_id']} 「{out['material']}」当前库存 {out['stock']} {out['unit']}，"
                          f"补货线 {out['reorder_point']}。{out['suggestion']}。")
            else:
                answer = (f"政策 {out['policy_code']}「{out['policy_name']}」{out['status']}：{out['rule']}"
                          f"（有效期至 {out['valid_until']}）。")
            return {"final_answer": answer, "citations": [], "handoff": False}
        # 工具失败：用知识库兜底
        if results:
            return {"final_answer": f"抱歉，工具调用未成功（{last.get('error')}）。知识库相关指引如下：\n{results[0]['text'][:500]}",
                    "citations": [r["doc_id"] for r in results], "handoff": False}

    if results:
        top = results[0]
        return {"final_answer": f"根据运营手册（类别：{top['category']}）：\n{top['text'][:600]}",
                "citations": [r["doc_id"] for r in results], "handoff": False}

    if handoff:
        return {"final_answer": "已将您的需求转接人工客服，区域经理稍后与您联系。",
                "citations": [], "handoff": True,
                "handoff_summary": f"用户问题：{query}"}

    return {"final_answer": "抱歉，知识库中暂未找到相关内容，已为您转人工跟进。",
            "citations": [], "handoff": True, "handoff_summary": f"未命中知识：{query}"}


def build_output_messages(state: Dict) -> List[dict]:
    """构造最终回答的完整消息（输出节点与 SSE 流式共用，保证两边 prompt 一致）。"""
    results = state.get("retrieval_results", [])
    tool_results = state.get("tool_results", [])
    context = state.get("context", "")
    messages = state.get("messages", [])

    tool_text = "\n".join(
        f"[工具:{t['name']}]\n{json.dumps(t['output'], ensure_ascii=False)}" for t in tool_results
    ) or "（本轮未调用工具）"

    user_prompt = (
        f"用户问题：{state.get('query')}\n\n"
        f"【检索上下文】\n{context or '（无检索结果）'}\n\n"
        f"【工具结果】\n{tool_text}\n\n"
        "请给出回答。若需转人工，在回答末尾说明。"
    )
    return [
        {"role": "system", "content": OUTPUT_PROMPT},
        *messages[-6:],
        {"role": "user", "content": user_prompt},
    ]


def output_node(state: Dict) -> Dict:
    intent = state.get("intent", "knowledge_query")
    if llm_client.offline:
        return _offline_answer(state)

    results = state.get("retrieval_results", [])
    citations = [r["doc_id"] for r in results]
    handoff = intent == "handoff"

    try:
        answer = llm_client.chat(build_output_messages(state), temperature=settings.llm_temperature, max_tokens=800)
    except Exception as e:
        answer = f"（生成失败，降级规则回答）{_offline_answer(state)['final_answer']}"

    if "转人工" in answer or intent == "handoff":
        handoff = True
    return {"final_answer": answer, "citations": citations, "handoff": handoff,
            "handoff_summary": f"用户问题：{state.get('query')}" if handoff else ""}
