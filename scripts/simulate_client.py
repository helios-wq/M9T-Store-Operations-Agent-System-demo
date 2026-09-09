"""命令行模拟客户端：不启动 HTTP 服务，直接走 Agent 全链路对话。

用法：python scripts/simulate_client.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.graph import run_agent          # noqa: E402
from app.llm.client import llm_client           # noqa: E402
from app.session import session_store           # noqa: E402

DEMO_QUESTIONS = [
    "收银机突然死机了怎么办",
    "我们店的制冰机故障，帮我报修一下",
    "可乐杯还有多少库存",
    "P02 会员日 88 折还有效吗",
    "顾客给了差评怎么处理",
    "我要找经理投诉，转人工",
]


def build_state(sid: str, store_id: str) -> dict:
    return {
        "session_id": sid, "store_id": store_id, "user_id": "console",
        "messages": [], "query": "",
        "intent": "knowledge_query", "category": "", "confidence": 0.0,
        "retrieval_results": [], "context": "",
        "tool_calls": [], "tool_results": [], "needs_retrieval": False,
        "final_answer": "", "citations": [], "handoff": False, "handoff_summary": "",
        "retrieval_rounds": 0, "max_retrieval_rounds": 2, "error": None,
    }


def main() -> None:
    sid = session_store.new_session()
    store_id = input("门店编号（回车默认 S001）：").strip() or "S001"
    state = build_state(sid, store_id)
    print(f"\n门店运营智能助手（会话 {sid} | 门店 {store_id} | "
          f"{'离线规则模式' if llm_client.offline else '在线 LLM 模式'}）")
    print("输入 exit 退出；输入 demo 体验演示问题。\n")

    while True:
        q = input("店长> ").strip()
        if not q:
            continue
        if q.lower() in ("exit", "quit"):
            break
        if q.lower() == "demo":
            for dq in DEMO_QUESTIONS:
                print(f"\n店长> {dq}")
                state.update(query=dq, messages=state["messages"] + [{"role": "user", "content": dq}],
                             retrieval_rounds=0, retry_retrieval=False, error=None)
                result = run_agent(state)
                print(f"助手> {result['final_answer']}")
                state["messages"] = result.get("messages", state["messages"]) + [
                    {"role": "assistant", "content": result.get("final_answer", "")}]
            continue

        state.update(query=q, messages=state["messages"] + [{"role": "user", "content": q}],
                     retrieval_rounds=0, retry_retrieval=False, error=None)
        result = run_agent(state)
        print(f"助手> {result['final_answer']}")
        if result.get("tool_results"):
            for t in result["tool_results"]:
                print(f"      [工具 {t['name']} ok={t['ok']}]")
        if result.get("citations"):
            print(f"      [来源] {', '.join(result['citations'])}")
        if result.get("handoff"):
            print("      [已转人工]")
        state["messages"] = result.get("messages", state["messages"]) + [
            {"role": "assistant", "content": result.get("final_answer", "")}]


if __name__ == "__main__":
    main()
