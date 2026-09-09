"""FastAPI 服务入口：REST 对话 / SSE 流式 / 企微回调 / 工单闭环 / 检索调试 / 健康检查 / 指标。"""
from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse

from .agent.graph import run_agent, stream_agent
from .agent.tools import notify_repair_dispatched
from .config import settings
from .db import (get_backend, get_repair, init_db, list_repairs,
                 save_chat_log, update_repair_status)
from .llm.client import llm_client
from .monitor import metrics
from .rag.retriever import retriever
from .rag.vector_store import get_vector_store
from .schemas import (ChatRequest, ChatResponse, HealthResponse,
                      RepairOut, RepairStatusRequest, RetrieveRequest, SSEEvent)
from .session import session_store
from .wecom import parse_message, verify_signature


def default_state(sid: str, store_id: str, user_id: str) -> dict:
    return {
        "session_id": sid, "store_id": store_id, "user_id": user_id,
        "messages": [], "query": "",
        "intent": "knowledge_query", "category": "", "confidence": 0.0,
        "retrieval_results": [], "context": "",
        "tool_calls": [], "tool_results": [], "needs_retrieval": False,
        "final_answer": "", "citations": [], "handoff": False, "handoff_summary": "",
        "retrieval_rounds": 0, "max_retrieval_rounds": 2, "error": None,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    store, kind = get_vector_store()
    if kind == "memory" and settings.index_path.exists():
        try:
            store.load(settings.index_path)
            print(f"[startup] 已加载向量索引：{settings.index_path}（{store.count()} 条 Chunk）")
        except Exception as e:
            print(f"[startup] 索引加载失败（{e}），请运行 python scripts/build_index.py")
    else:
        print("[startup] 未发现本地索引，请先运行 python scripts/build_index.py 构建 RAG 索引")
    yield


app = FastAPI(title="连锁门店运营智能助手", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------- REST 对话 ----------------
@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    t0 = time.time()
    sid = req.session_id or session_store.new_session()
    state = session_store.get(sid) or default_state(sid, req.store_id, req.user_id)
    state.update(
        session_id=sid, store_id=req.store_id, user_id=req.user_id,
        query=req.message,
        messages=state.get("messages", []) + [{"role": "user", "content": req.message}],
        retrieval_rounds=0, retry_retrieval=False, error=None,
    )
    result = run_agent(state)
    messages = result.get("messages", state.get("messages", []))
    messages = messages + [{"role": "assistant", "content": result.get("final_answer", "")}]
    result["messages"] = messages
    session_store.set(sid, result)

    elapsed = int((time.time() - t0) * 1000)
    is_error = bool(result.get("error")) or result.get("handoff")
    metrics.record(elapsed, is_error=is_error)
    metrics.check_alert()
    save_chat_log({
        "session_id": sid, "user_id": req.user_id, "store_id": req.store_id,
        "query": req.message, "intent": result.get("intent", ""),
        "answer": result.get("final_answer", ""), "handoff": result.get("handoff", False),
        "latency_ms": elapsed,
    })
    return ChatResponse(
        session_id=sid,
        intent=result.get("intent", ""),
        answer=result.get("final_answer", ""),
        citations=result.get("citations", []),
        tool_results=result.get("tool_results", []),
        handoff=result.get("handoff", False),
        elapsed_ms=elapsed,
    )


# ---------------- SSE 流式对话 ----------------
@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    async def event_gen():
        t0 = time.time()
        sid = req.session_id or session_store.new_session()
        state = session_store.get(sid) or default_state(sid, req.store_id, req.user_id)
        state.update(
            session_id=sid, store_id=req.store_id, user_id=req.user_id,
            query=req.message,
            messages=state.get("messages", []) + [{"role": "user", "content": req.message}],
            retrieval_rounds=0, retry_retrieval=False, error=None,
        )
        final_answer = ""
        async for event, data in stream_agent(state):
            if event == "done":
                final_answer = data.get("final_answer", "")
                metrics.record(data.get("elapsed_ms", 0), is_error=state.get("handoff", False))
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        # 落库
        messages = state.get("messages", []) + [{"role": "assistant", "content": final_answer}]
        state["messages"] = messages
        session_store.set(sid, state)
        save_chat_log({
            "session_id": sid, "user_id": req.user_id, "store_id": req.store_id,
            "query": req.message, "intent": state.get("intent", ""),
            "answer": final_answer, "handoff": state.get("handoff", False),
            "latency_ms": int((time.time() - t0) * 1000),
        })

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------------- 会话历史 ----------------
@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    state = session_store.get(session_id) or {}
    return {"session_id": session_id, "messages": state.get("messages", []),
            "intent": state.get("intent", ""), "handoff": state.get("handoff", False)}


# ---------------- 检索调试 ----------------
@app.post("/api/retrieve")
def retrieve(req: RetrieveRequest):
    results = retriever.retrieve(req.query, top_k=req.top_k, query_category=None)
    return {"query": req.query, "top_k": req.top_k,
            "results": [r.to_dict() for r in results]}


# ---------------- 报修工单闭环 ----------------
# 状态机：已受理 → 已派单 → 维修中 → 已解决 → 已关闭（店长确认）
# 企微群里可发「RX单号 状态词」直接推进（维修工上报 / 店长确认）

_REPAIR_CMD = re.compile(r"(RX\d{8})\s*(已受理|已派单|维修中|已解决|已关闭)")


def _notify_if_dispatched(record: dict) -> None:
    """状态推进到「已派单」时推送维修群（通知维修组接单处理），失败不阻断主流程。"""
    if record and record.get("status") == "已派单":
        err = notify_repair_dispatched(record)
        if err:  # pragma: no cover
            print(f"[notify] 派单推送失败：{err}")


@app.get("/api/repairs", response_model=list[RepairOut])
def repairs_list(store_id: str | None = None, limit: int = 20):
    return list_repairs(store_id=store_id, limit=min(limit, 100))


@app.get("/api/repairs/{order_no}", response_model=RepairOut)
def repair_detail(order_no: str):
    record = get_repair(order_no)
    if not record:
        raise HTTPException(status_code=404, detail=f"工单 {order_no} 不存在")
    return record


@app.post("/api/repairs/{order_no}/status", response_model=RepairOut)
def repair_update(order_no: str, req: RepairStatusRequest):
    ok, msg, record = update_repair_status(order_no, req.status, actor=req.actor, confirm=req.confirm)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    _notify_if_dispatched(record)
    return record


# ---------------- 企业微信回调 ----------------
@app.get("/wecom/callback")
def wecom_verify(timestamp: str, nonce: str, echostr: str, msg_signature: str = ""):
    if verify_signature(settings.wecom_token, timestamp, nonce, echostr, msg_signature):
        return PlainTextResponse(echostr)
    return PlainTextResponse("signature error", status_code=403)


@app.post("/wecom/callback")
async def wecom_msg(request: Request):
    body = (await request.body()).decode("utf-8")
    msg = parse_message(body)
    if not msg:
        return PlainTextResponse("success")
    # 1) 优先识别工单状态指令：维修工/店长在群里发「RX单号 已解决」等
    m = _REPAIR_CMD.search(msg["content"])
    if m:
        ok, text, record = update_repair_status(m.group(1), m.group(2),
                                                actor=msg.get("from_user", "wecom"))
        if ok:
            _notify_if_dispatched(record)
        return PlainTextResponse(text if ok else f"更新失败：{text}")
    # 2) 否则走正常 Agent 对话
    reply = _agent_runner(msg["content"], msg.get("from_user", "wecom"))
    return PlainTextResponse(reply)


def _agent_runner(query: str, user_id: str = "wecom", store_id: str = "S001") -> str:
    """企微消息 → Agent → 回复文本（复用无 HTTP 依赖的链路）。"""
    sid = session_store.new_session()
    state = default_state(sid, store_id, user_id)
    state["query"] = query
    state["messages"] = [{"role": "user", "content": query}]
    result = run_agent(state)
    return result.get("final_answer", "")


# ---------------- 健康检查 / 指标 ----------------
@app.get("/healthz", response_model=HealthResponse)
def healthz():
    _, kind = get_vector_store()
    return HealthResponse(
        status="ok",
        llm_online=not llm_client.offline,
        vector_store=kind,
        session_store=session_store.backend,
        db_store=get_backend(),
    )


@app.get("/metrics")
def prom_metrics():
    return PlainTextResponse(metrics.prometheus_text())
