"""评测脚本：计算 4 个核心指标（对应简历量化成果）。

- 意图准确率   ：意图识别正确比例
- 工具调用准确率：工具类用例中正确调用期望工具的比例
- 任务完成率   ：工具调用成功（ok=True）的比例
- Top-3 召回率 ：检索类用例中 ground_truth 文档进入 Top-3 的比例
- 幻觉率（近似）：回答与检索上下文的重合度低于阈值的比例（仅离线模式可精确计算）

用法：python -m app.eval.run_eval [min_cases]
"""
from __future__ import annotations

import sys
from typing import Dict, List

from ..agent.graph import run_agent
from ..config import settings
from ..llm.client import llm_client
from ..rag.retriever import retriever
from .eval_cases import get_eval_cases


def _bigrams(text: str) -> set:
    chars = [c for c in text if c.strip()]
    return {"".join(chars[i:i + 2]) for i in range(len(chars) - 1)}


def _grounding_overlap(answer: str, context: str) -> float:
    a, c = _bigrams(answer), _bigrams(context)
    if not a:
        return 1.0
    return len(a & c) / len(a)


def _run_case(case: dict, store_id: str = "S001") -> dict:
    if case["type"] == "retrieval":
        results = retriever.retrieve(case["question"], top_k=3, query_category=case.get("category"))
        hit_ids = {r.doc_id for r in results}
        return {
            "case": case["id"], "type": "retrieval",
            "recall_hit": case["ground_truth_doc_id"] in hit_ids,
            "intent_hit": None,
            "tool_hit": None,
            "completion": None,
            "top_docs": sorted(hit_ids)[:3],
        }
    # tool / handoff：跑一轮 Agent
    state = {
        "session_id": f"eval-{case['id']}", "store_id": store_id, "user_id": "eval",
        "messages": [], "query": case["question"],
        "intent": "knowledge_query", "category": "", "confidence": 0.0,
        "retrieval_results": [], "context": "",
        "tool_calls": [], "tool_results": [], "needs_retrieval": False,
        "final_answer": "", "citations": [], "handoff": False, "handoff_summary": "",
        "retrieval_rounds": 0, "max_retrieval_rounds": 2, "error": None,
    }
    result = run_agent(state)
    tool_names = [t.get("name") for t in result.get("tool_calls", [])]
    tool_ok = all(t.get("ok") for t in result.get("tool_results", [])) if result.get("tool_results") else False
    intent_hit = result.get("intent") == case["intent"]
    if case["type"] == "tool":
        tool_hit = case["expected_tool"] in tool_names
        return {
            "case": case["id"], "type": "tool",
            "recall_hit": None, "intent_hit": intent_hit,
            "tool_hit": tool_hit, "completion": tool_hit and tool_ok,
            "tool_names": tool_names,
            "answer": result.get("final_answer", ""),
            "context": result.get("context", ""),
        }
    return {
        "case": case["id"], "type": "handoff",
        "recall_hit": None, "intent_hit": intent_hit,
        "tool_hit": None, "completion": result.get("handoff", False),
        "answer": result.get("final_answer", ""),
    }


def summarize(results: List[dict]) -> Dict:
    n = len(results)
    retrieval = [r for r in results if r["type"] == "retrieval"]
    tools = [r for r in results if r["type"] == "tool"]
    handoffs = [r for r in results if r["type"] == "handoff"]
    intent_cases = [r for r in results if r["intent_hit"] is not None]
    completion_cases = [r for r in results if r["completion"] is not None]

    recall = sum(1 for r in retrieval if r["recall_hit"]) / len(retrieval) if retrieval else 0.0
    intent_acc = sum(1 for r in intent_cases if r["intent_hit"]) / len(intent_cases) if intent_cases else 0.0
    tool_acc = sum(1 for r in tools if r["tool_hit"]) / len(tools) if tools else 0.0
    completion = sum(1 for r in completion_cases if r["completion"]) / len(completion_cases) if completion_cases else 0.0
    handoff_rate = sum(1 for r in handoffs if r["completion"]) / len(handoffs) if handoffs else 0.0

    # 幻觉率（近似）：只对离线模式评估（在线回答需人工/LLM 裁判）
    hallucination = None
    if llm_client.offline:
        graded = [r for r in results if r.get("answer") and r.get("context")]
        if graded:
            bad = sum(1 for r in graded if _grounding_overlap(r["answer"], r["context"]) < 0.35)
            hallucination = bad / len(graded)

    return {
        "cases": n,
        "recall@3": round(recall, 4),
        "intent_accuracy": round(intent_acc, 4),
        "tool_accuracy": round(tool_acc, 4),
        "task_completion_rate": round(completion, 4),
        "handoff_rate": round(handoff_rate, 4),
        "hallucination_rate": round(hallucination, 4) if hallucination is not None else None,
        "mode": "offline" if llm_client.offline else "online",
    }


def main(min_cases: int = 120) -> None:
    cases = get_eval_cases(min_cases)
    print(f"评测集规模：{len(cases)} 条（意图识别 {sum(1 for c in cases if c['type'] != 'retrieval')} 条 + 检索 {sum(1 for c in cases if c['type'] == 'retrieval')} 条）")
    print(f"运行模式：{'离线规则（未配置 LLM Key）' if llm_client.offline else '在线 LLM'}\n")
    results = [_run_case(c, store_id=f"S{1 + (abs(hash(c['id'])) % 200):03d}") for c in cases]
    summary = summarize(results)
    print("=" * 46)
    print(f"  召回率@3            : {summary['recall@3']:.2%}")
    print(f"  意图准确率          : {summary['intent_accuracy']:.2%}")
    print(f"  工具调用准确率      : {summary['tool_accuracy']:.2%}")
    print(f"  任务完成率          : {summary['task_completion_rate']:.2%}")
    print(f"  转人工覆盖率        : {summary['handoff_rate']:.2%}")
    if summary["hallucination_rate"] is not None:
        print(f"  幻觉率（离线近似）  : {summary['hallucination_rate']:.2%}")
    print("=" * 46)
    # 输出未命中的用例便于复盘
    misses = [r for r in results if r["type"] == "retrieval" and not r["recall_hit"]]
    for m in misses[:10]:
        print(f"  [召回未命中] {m['case']} 期望 {m['top_docs']}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
