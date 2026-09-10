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
                 save_chat_log, update_repair_status,
                 list_inventory, get_inventory, upsert_inventory,
                 list_promotions, get_promotion, upsert_promotion,
                 list_stores, get_store, upsert_store,
                 list_devices, get_device, upsert_device,
                 list_staff, get_staff, upsert_staff)
from .llm.client import llm_client
from .monitor import metrics
from .rag.retriever import retriever
from .rag.vector_store import get_vector_store
from .schemas import (ChatRequest, ChatResponse, HealthResponse,
                      RepairOut, RepairStatusRequest, RetrieveRequest, SSEEvent)
from pydantic import BaseModel
from typing import Optional
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


# ================================================================
# 主数据管理接口（库存 / 促销 / 门店 / 设备 / 员工）
# 生产环境建议加鉴权，当前演示版本开放读写
# ================================================================

# ---------------- 请求体模型 ----------------
class InventoryRequest(BaseModel):
    store_id: str
    material: str
    stock: int
    unit: str = "个"
    reorder_point: int = 0

class PromotionRequest(BaseModel):
    promo_code: str
    name: str
    rule: str
    status: str = "生效中"
    valid_from: str = ""
    valid_until: str = ""

class StoreRequest(BaseModel):
    store_id: str
    name: str = ""
    address: str = ""
    phone: str = ""
    manager: str = ""
    status: str = "营业中"

class DeviceRequest(BaseModel):
    device_id: str
    store_id: str
    device_type: str
    brand: str = ""
    model: str = ""
    purchase_date: str = ""
    warranty_until: str = ""
    status: str = "正常"

class StaffRequest(BaseModel):
    staff_id: str
    name: str
    role: str = "店员"
    phone: str = ""
    store_id: str = ""
    status: str = "在职"


# ---------------- 库存管理 ----------------
@app.get("/api/inventory")
def api_list_inventory(store_id: Optional[str] = None, limit: int = 100):
    """物料库存列表（可按门店过滤）。"""
    return list_inventory(store_id=store_id, limit=min(limit, 500))


@app.get("/api/inventory/{store_id}/{material}")
def api_get_inventory(store_id: str, material: str):
    """查询指定门店指定物料的库存。"""
    record = get_inventory(store_id, material)
    if not record:
        raise HTTPException(status_code=404, detail=f"未找到 {store_id} {material}")
    return record


@app.post("/api/inventory")
def api_upsert_inventory(req: InventoryRequest):
    """新增或更新物料库存（upsert）。"""
    upsert_inventory(req.store_id, req.material, req.stock, req.unit, req.reorder_point)
    return {"ok": True, "store_id": req.store_id, "material": req.material, "stock": req.stock}


# ---------------- 促销管理 ----------------
@app.get("/api/promotions")
def api_list_promotions(status: Optional[str] = None, limit: int = 50):
    """促销政策列表（可按状态过滤）。"""
    return list_promotions(status=status, limit=min(limit, 200))


@app.get("/api/promotions/{promo_code}")
def api_get_promotion(promo_code: str):
    """查询指定促销政策详情。"""
    record = get_promotion(promo_code)
    if not record:
        raise HTTPException(status_code=404, detail=f"未找到促销政策 {promo_code}")
    return record


@app.post("/api/promotions")
def api_upsert_promotion(req: PromotionRequest):
    """新增或更新促销政策（upsert）。"""
    upsert_promotion(req.promo_code, req.name, req.rule, req.status, req.valid_from, req.valid_until)
    return {"ok": True, "promo_code": req.promo_code, "name": req.name, "status": req.status}


# ---------------- 门店管理 ----------------
@app.get("/api/stores")
def api_list_stores(status: Optional[str] = None, limit: int = 200):
    """门店列表（可按状态过滤）。"""
    return list_stores(status=status, limit=min(limit, 500))


@app.get("/api/stores/{store_id}")
def api_get_store(store_id: str):
    """查询指定门店详情。"""
    record = get_store(store_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"未找到门店 {store_id}")
    return record


@app.post("/api/stores")
def api_upsert_store(req: StoreRequest):
    """新增或更新门店信息（upsert）。"""
    upsert_store(req.store_id, req.name, req.address, req.phone, req.manager, req.status)
    return {"ok": True, "store_id": req.store_id, "name": req.name, "status": req.status}


# ---------------- 设备管理 ----------------
@app.get("/api/devices")
def api_list_devices(store_id: Optional[str] = None, limit: int = 100):
    """设备清单（可按门店过滤）。"""
    return list_devices(store_id=store_id, limit=min(limit, 500))


@app.get("/api/devices/{device_id}")
def api_get_device(device_id: str):
    """查询指定设备详情。"""
    record = get_device(device_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"未找到设备 {device_id}")
    return record


@app.post("/api/devices")
def api_upsert_device(req: DeviceRequest):
    """新增或更新设备信息（upsert）。"""
    upsert_device(req.device_id, req.store_id, req.device_type, req.brand, req.model,
                   req.purchase_date, req.warranty_until, req.status)
    return {"ok": True, "device_id": req.device_id, "store_id": req.store_id, "device_type": req.device_type}


# ---------------- 员工管理 ----------------
@app.get("/api/staff")
def api_list_staff(role: Optional[str] = None, store_id: Optional[str] = None, limit: int = 100):
    """员工列表（可按角色/门店过滤）。"""
    return list_staff(role=role, store_id=store_id, limit=min(limit, 500))


@app.get("/api/staff/{staff_id}")
def api_get_staff(staff_id: str):
    """查询指定员工详情。"""
    record = get_staff(staff_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"未找到员工 {staff_id}")
    return record


@app.post("/api/staff")
def api_upsert_staff(req: StaffRequest):
    """新增或更新员工信息（upsert）。"""
    upsert_staff(req.staff_id, req.name, req.role, req.phone, req.store_id, req.status)
    return {"ok": True, "staff_id": req.staff_id, "name": req.name, "role": req.role}
