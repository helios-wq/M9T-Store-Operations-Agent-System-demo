"""Agent 状态机编排：LangGraph 图 + 手动执行器（降级）+ 事件流。

- build_graph(): 用 LangGraph 构建 4 节点状态机并 compile；
- run_agent(state): 完整跑一轮（LangGraph 优先，异常降级手动执行器）；
- stream_agent(state): 异步事件流生成器，供 SSE 接口逐事件下发
  （intent → retrieval/tool → answer_start → answer_delta* → done）。
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, Dict, List, Tuple

from ..config import settings
from ..llm.client import llm_client
from .nodes import (build_output_messages, intent_node, output_node,
                    retrieve_node, tool_node)
from .state import AgentState

END = "__end__"


# ---------------- 路由函数 ----------------
def _route_after_intent(state: Dict) -> str:
    intent = state.get("intent")
    if intent in ("handoff", "chat"):
        return "output"
    if intent in ("repair_tool", "inventory_tool", "promotion_tool"):
        return "tool"
    return "retrieve"


def _route_after_tool(state: Dict) -> str:
    return "retrieve" if state.get("needs_retrieval") else "output"


def _route_after_output(state: Dict) -> str:
    # 步骤回退：输出节点发现上下文不足时重新检索（上限 2 轮）
    if (state.get("retry_retrieval") and
            state.get("retrieval_rounds", 0) < state.get("max_retrieval_rounds", 2)):
        return "retrieve"
    return END


# ---------------- LangGraph 图 ----------------
def build_graph():
    from langgraph.graph import END as LG_END, START, StateGraph
    g = StateGraph(AgentState)
    g.add_node("intent", intent_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("tool", tool_node)
    g.add_node("output", output_node)
    g.add_edge(START, "intent")
    g.add_conditional_edges("intent", _route_after_intent,
                            {"retrieve": "retrieve", "tool": "tool", "output": "output"})
    g.add_conditional_edges("tool", _route_after_tool,
                            {"retrieve": "retrieve", "output": "output"})
    g.add_conditional_edges("output", _route_after_output,
                            {"retrieve": "retrieve", "end": LG_END})
    return g.compile()


# ---------------- 手动执行器（LangGraph 不可用或流式时使用） ----------------
def _manual_run(state: Dict) -> Dict:
    state = dict(state)
    state.update(intent_node(state))
    route = _route_after_intent(state)
    guard = 0
    while route != "output" and route != END and guard < 10:
        guard += 1
        if route == "retrieve":
            state.update(retrieve_node(state))
            route = "output"
        elif route == "tool":
            state.update(tool_node(state))
            route = _route_after_tool(state)
    state.update(output_node(state))
    route = _route_after_output(state)
    if route == "retrieve" and guard < 10:
        state.update(retrieve_node(state))
        state.update(output_node(state))
    return state


def run_agent(state: Dict) -> Dict:
    """同步完整执行一轮（在线评估/脚本用）。"""
    if settings.offline:
        return _manual_run(state)
    try:
        graph = build_graph()
        return graph.invoke(dict(state))
    except Exception:
        return _manual_run(state)


# ---------------- 事件流（SSE） ----------------
async def stream_agent(state: Dict) -> AsyncGenerator[Tuple[str, dict], None]:
    """按事件逐个产出：intent / retrieval / tool / answer_start / answer_delta* / done。"""
    state = dict(state)
    start = time.time()

    # 1) 意图识别
    state.update(intent_node(state))
    yield ("intent", {
        "intent": state.get("intent"),
        "category": state.get("category"),
        "confidence": state.get("confidence"),
    })

    # 2) 路由执行
    route = _route_after_intent(state)
    guard = 0
    while route != "output" and guard < 10:
        guard += 1
        if route == "retrieve":
            state.update(retrieve_node(state))
            yield ("retrieval", {
                "results": state.get("retrieval_results", []),
                "context_len": len(state.get("context", "")),
                "round": state.get("retrieval_rounds", 1),
            })
            route = "output"
        elif route == "tool":
            state.update(tool_node(state))
            yield ("tool", {
                "calls": state.get("tool_calls", []),
                "results": state.get("tool_results", []),
                "degrade_to_retrieval": state.get("needs_retrieval", False),
            })
            route = _route_after_tool(state)

    # 3) 输出
    state.update(output_node(state))
    yield ("answer_start", {
        "citations": state.get("citations", []),
        "handoff": state.get("handoff", False),
    })

    # 4) 流式答案：在线走 LLM token 流，离线整体吐出
    full_text = state.get("final_answer", "")
    if llm_client.offline:
        yield ("answer_delta", full_text)
    else:
        try:
            async for chunk in llm_client.achat_stream(build_output_messages(state)):
                full_text += chunk
                yield ("answer_delta", chunk)
        except Exception:
            # 流式失败则回退到已生成的完整回答
            if not full_text:
                full_text = state.get("final_answer", "")
            yield ("answer_delta", full_text)
    state["final_answer"] = full_text

    yield ("done", {
        "session_id": state.get("session_id"),
        "intent": state.get("intent"),
        "elapsed_ms": int((time.time() - start) * 1000),
        "final_answer": full_text,
    })
