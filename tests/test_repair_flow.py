"""报修工单闭环：状态机流转 + 企微指令 + HTTP 接口。"""
import pytest
from fastapi.testclient import TestClient

from app.agent.tools import report_repair
from app.db import (get_repair, init_db, list_repairs,
                    update_repair_status)
from app.main import app

init_db()


@pytest.fixture()
def order_no():
    """创建一张工单并返回单号（每次独立，避免状态污染）。"""
    r = report_repair("S002", "冷藏冰箱", "不制冷")
    assert r["ok"] is True
    return r["order_no"]


# ---------------- 状态机（db 层） ----------------

def test_create_then_flow_to_closed(order_no):
    """合法路径：已受理 → 已派单 → 维修中 → 已解决 → 已关闭（店长确认）。"""
    for status, actor, confirm in [
        ("已派单", "维修组-李工", False),
        ("维修中", "维修组-李工", False),
        ("已解决", "维修组-李工", False),
        ("已关闭", "店长-王店", True),
    ]:
        ok, msg, record = update_repair_status(order_no, status, actor=actor, confirm=confirm)
        assert ok, msg
        assert record["status"] == status
    record = get_repair(order_no)
    assert record["confirmed"] is True
    assert record["actor"] == "店长-王店"


def test_illegal_skip_transition(order_no):
    """不可跳级：已受理 不能直接 → 已解决。"""
    ok, msg, _ = update_repair_status(order_no, "已解决")
    assert ok is False
    assert "非法流转" in msg
    assert get_repair(order_no)["status"] == "已受理"


def test_unknown_order():
    ok, msg, _ = update_repair_status("RX99999999", "已派单")
    assert ok is False
    assert "不存在" in msg


def test_close_requires_confirm(order_no):
    """维修工不能自行关闭工单：已解决 → 已关闭 必须 confirm。"""
    update_repair_status(order_no, "已派单")
    update_repair_status(order_no, "维修中")
    update_repair_status(order_no, "已解决", actor="维修组-李工")
    ok, msg, _ = update_repair_status(order_no, "已关闭", actor="维修组-李工", confirm=False)
    assert ok is False
    assert "店长确认" in msg
    assert get_repair(order_no)["status"] == "已解决"


def test_invalid_status_word(order_no):
    ok, msg, _ = update_repair_status(order_no, "随便")
    assert ok is False
    assert "无效状态" in msg


def test_list_repairs_filters_store():
    report_repair("S003", "炸炉", "不加热")
    rows = list_repairs(store_id="S003", limit=10)
    assert rows and all(r["store_id"] == "S003" for r in rows)


# ---------------- 派单企微推送 ----------------

def test_dispatched_pushes_wecom(monkeypatch):
    """推进到「已派单」时推送维修群，内容含设备与故障描述；失败不抛异常。"""
    from app.agent import tools
    sent = {}
    monkeypatch.setattr(tools, "send_wecom_message", lambda url, text: sent.update(url=url, text=text))
    monkeypatch.setattr(tools.settings, "wecom_webhook", "https://fake-webhook")
    record = {
        "order_no": "RX12345678", "store_id": "S008", "device": "收银机",
        "problem_desc": "收银机死机，无法结账", "priority": "普通", "sla": "24小时内响应",
        "status": "已派单",
    }
    err = tools.notify_repair_dispatched(record)
    assert err is None
    assert "RX12345678" in sent["text"] and "已派单" in sent["text"]
    assert "收银机" in sent["text"] and "无法结账" in sent["text"]


def test_dispatched_push_skips_without_webhook(monkeypatch):
    """未配置 WECOM_WEBHOOK 时静默跳过（不抛异常）。"""
    from app.agent import tools
    called = []
    monkeypatch.setattr(tools, "send_wecom_message", lambda *a, **k: called.append(a))
    monkeypatch.setattr(tools.settings, "wecom_webhook", "")
    err = tools.notify_repair_dispatched({"order_no": "RX1", "store_id": "S001",
                                          "device": "空调", "problem_desc": "不制冷"})
    assert err is None
    assert called == []


def test_wecom_callback_dispatch_triggers_push(monkeypatch):
    """企微指令「RX单号 已派单」推进状态并触发派单推送。"""
    from app.agent import tools
    from app.main import _notify_if_dispatched
    from app import db
    sent = []
    monkeypatch.setattr(tools, "send_wecom_message", lambda url, text: sent.append(text))
    monkeypatch.setattr(tools.settings, "wecom_webhook", "https://fake-webhook")
    monkeypatch.setattr(db.settings, "wecom_webhook", "https://fake-webhook")
    r = report_repair("S005", "空调", "制冷失效")
    ok, msg, record = update_repair_status(r["order_no"], "已派单", actor="维修组-李工")
    assert ok
    _notify_if_dispatched(record)
    assert sent and "已派单" in sent[-1]
    assert r["order_no"] in sent[-1]


# ---------------- HTTP 接口 ----------------

def test_status_api_flow(order_no):
    with TestClient(app) as client:
        # 详情
        r = client.get(f"/api/repairs/{order_no}")
        assert r.status_code == 200
        assert r.json()["status"] == "已受理"
        # 推进到维修中
        r = client.post(f"/api/repairs/{order_no}/status",
                        json={"status": "已派单", "actor": "维修组-李工"})
        assert r.status_code == 200, r.text
        r = client.post(f"/api/repairs/{order_no}/status",
                        json={"status": "维修中", "actor": "维修组-李工"})
        assert r.status_code == 200
        # 非法跳级 → 400
        r = client.post(f"/api/repairs/{order_no}/status",
                        json={"status": "已关闭", "confirm": False})
        assert r.status_code == 400
        assert "非法流转" in r.json()["detail"]
        # 已解决 → 已关闭 缺确认 → 400
        client.post(f"/api/repairs/{order_no}/status", json={"status": "已解决", "actor": "维修组-李工"})
        r = client.post(f"/api/repairs/{order_no}/status",
                        json={"status": "已关闭", "actor": "维修组-李工", "confirm": False})
        assert r.status_code == 400
        assert "店长确认" in r.json()["detail"]
        # 店长确认关闭 → 200
        r = client.post(f"/api/repairs/{order_no}/status",
                        json={"status": "已关闭", "actor": "店长-王店", "confirm": True})
        assert r.status_code == 200
        assert r.json()["confirmed"] is True
        # 404
        r = client.get("/api/repairs/RX99999999")
        assert r.status_code == 404


def test_status_api_unknown():
    with TestClient(app) as client:
        r = client.post("/api/repairs/RX99999999/status", json={"status": "已派单"})
        assert r.status_code == 400
        assert "不存在" in r.json()["detail"]
