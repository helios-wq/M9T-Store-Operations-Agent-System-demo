"""LangGraph 状态定义：Agent 状态机流转的全部字段。"""
from __future__ import annotations

from typing import List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # ---- 会话上下文 ----
    session_id: str
    store_id: str
    user_id: str
    messages: List[dict]              # [{role, content}] 历史对话
    query: str                        # 本轮用户消息

    # ---- 意图识别节点输出 ----
    intent: str                       # repair_tool / inventory_tool / promotion_tool / knowledge_query / handoff / chat
    category: str                     # 问题类别（用于检索过滤与工具选择）
    confidence: float

    # ---- 检索节点输出 ----
    retrieval_results: List[dict]     # RetrievalResult.to_dict()
    context: str                      # 供 LLM 引用的上下文

    # ---- 工具节点输出 ----
    tool_calls: List[dict]            # [{name, arguments, raw}]
    tool_results: List[dict]          # [{name, ok, output, error}]
    needs_retrieval: bool             # 工具失败后降级检索的标志

    # ---- 输出节点 ----
    final_answer: str
    citations: List[str]
    handoff: bool                     # 是否转人工
    handoff_summary: str

    # ---- 流程控制 ----
    retrieval_rounds: int             # 检索轮数（防死循环）
    max_retrieval_rounds: int
    error: Optional[str]
