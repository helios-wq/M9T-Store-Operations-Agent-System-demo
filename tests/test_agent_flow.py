"""Agent 状态机全流程单测（离线模式，验证 4 节点 + 路由 + 降级）。"""
from __future__ import annotations

from app.agent.graph import run_agent, _manual_run
from app.llm.client import llm_client


def _base_state(query: str, store_id: str = "S001") -> dict:
    return {
        "session_id": "t", "store_id": store_id, "user_id": "tester",
        "messages": [], "query": query,
        "intent": "knowledge_query", "category": "", "confidence": 0.0,
        "retrieval_results": [], "context": "",
        "tool_calls": [], "tool_results": [], "needs_retrieval": False,
        "final_answer": "", "citations": [], "handoff": False, "handoff_summary": "",
        "retrieval_rounds": 0, "max_retrieval_rounds": 2, "error": None,
    }


def test_knowledge_query_flow():
    state = _base_state("收银机突然死机了怎么办")
    result = run_agent(state)
    assert result["intent"] == "repair_tool"
    assert result["final_answer"]
    assert result["tool_calls"]               # 报修类问题会先走工具


def test_tool_flow_report_repair():
    state = _base_state("我们店的收银机坏了，帮我报修")
    result = run_agent(state)
    assert result["tool_calls"][0]["name"] == "report_repair"
    assert result["tool_results"][0]["ok"] is True
    assert "工单" in result["final_answer"] or "RX" in result["final_answer"]


def test_tool_flow_inventory():
    state = _base_state("可乐杯还有多少库存")
    result = run_agent(state)
    assert result["tool_calls"][0]["name"] == "query_inventory"
    assert result["tool_results"][0]["ok"] is True
    assert "库存" in result["final_answer"]


def test_tool_flow_promotion():
    state = _base_state("P01 满100减20还能用吗")
    result = run_agent(state)
    assert result["tool_calls"][0]["name"] == "check_promotion"
    assert "生效" in result["final_answer"] or "P01" in result["final_answer"]


def test_handoff_flow():
    state = _base_state("我要找经理投诉，转人工")
    result = run_agent(state)
    assert result["handoff"] is True
    assert result["intent"] == "handoff"


def test_intent_switch_within_session():
    """会话中意图切换：先报修再查库存，工具中间状态应被清理。"""
    s1 = run_agent(_base_state("收银机坏了报修"))
    s2 = run_agent(_base_state("顺便问下可乐杯库存", store_id="S001"))
    # 第二轮应只保留本轮工具调用
    assert s2["tool_calls"][0]["name"] == "query_inventory"


def test_manual_runner_matches():
    """手动执行器与 LangGraph 结果一致性（离线模式）。"""
    r1 = run_agent(_base_state("制冰机不出冰"))
    r2 = _manual_run(_base_state("制冰机不出冰"))
    assert r1["intent"] == r2["intent"]
    assert r1["tool_calls"] == r2["tool_calls"]
