"""企业微信接入：
1. 消息回调验签（明文模式）：GET /wecom/callback?msg_signature=&timestamp=&nonce=&echostr= 校验后回显 echostr；
2. 消息解析：POST 收到 XML 文本消息；
3. 机器人回复：群机器人 Webhook 发送 markdown/text。

（生产环境可升级为加密模式与自建应用 API，本组件保持明文回调 + 群机器人，
便于本地用 curl / 企微测试工具直接验证。）
"""
from __future__ import annotations

import hashlib
import time
from typing import Optional
from xml.etree import ElementTree as ET

import httpx

from .config import settings


# ---------------- 验签 ----------------
def verify_signature(token: str, timestamp: str, nonce: str, echostr: str, msg_signature: str) -> bool:
    """企业微信回调验签：token/timestamp/nonce 字典序排序拼接后 SHA1。"""
    if not msg_signature:
        return True  # 明文模式可不带签名（演示）
    raw = "".join(sorted([token, timestamp, nonce]))
    sig = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return sig == msg_signature


# ---------------- 消息解析 ----------------
def parse_message(xml_text: str) -> Optional[dict]:
    """解析企微文本消息 XML。"""
    try:
        root = ET.fromstring(xml_text)
        msg_type = root.findtext("MsgType", "")
        if msg_type != "text":
            return None
        return {
            "from_user": root.findtext("FromUserName", ""),
            "to_user": root.findtext("ToUserName", ""),
            "content": root.findtext("Content", "").strip(),
            "msg_id": root.findtext("MsgId", ""),
            "create_time": root.findtext("CreateTime", ""),
        }
    except Exception:
        return None


# ---------------- 群机器人回复 ----------------
def send_wecom_message(webhook_url: str, content: str, mentioned: list | None = None) -> dict:
    """向企微群机器人 Webhook 发送文本消息。"""
    payload = {
        "msgtype": "text",
        "text": {"content": content, "mentioned_list": mentioned or []},
    }
    resp = httpx.post(webhook_url, json=payload, timeout=10)
    return {"status_code": resp.status_code, "body": resp.json()}


def handle_wecom_message(msg: dict, agent_runner) -> dict:
    """把企微消息转成 Agent 调用。agent_runner: fn(query, store_id, user_id) -> dict(answer,...)"""
    result = agent_runner(msg["content"])
    return {
        "reply": result.get("answer", ""),
        "session_id": result.get("session_id", ""),
        "intent": result.get("intent", ""),
        "handoff": result.get("handoff", False),
    }
