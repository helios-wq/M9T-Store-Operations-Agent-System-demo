"""API 请求/响应模型（Pydantic v2）。"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: Optional[str] = None  # 不传则服务端新建
    message: str = Field(..., min_length=1, description="用户消息")
    store_id: str = "S001"            # 当前门店编号
    user_id: str = "anonymous"        # 企微用户标识


class ChatResponse(BaseModel):
    session_id: str
    intent: str
    answer: str
    citations: List[str] = Field(default_factory=list)
    tool_results: List[dict] = Field(default_factory=list)
    handoff: bool = False
    elapsed_ms: int = 0


class SSEEvent(BaseModel):
    """SSE 事件载荷：event 字段区分 intent/retrieval/tool/answer/done。"""
    event: str
    data: dict


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 3
    store_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    llm_online: bool
    vector_store: str
    session_store: str
    db_store: str


class RepairStatusRequest(BaseModel):
    status: str = Field(..., description="目标状态：已派单/维修中/已解决/已关闭")
    actor: str = "system"          # 操作人（维修工/店长/系统）
    confirm: bool = False          # 关闭工单时的店长确认标记


class RepairOut(BaseModel):
    order_no: str
    store_id: str
    device: str
    problem_desc: str
    priority: str
    status: str
    sla: str
    actor: str = ""
    confirmed: bool = False
    created_at: Optional[datetime] = None
