"""内部 API 工具单测。"""
from app.agent.tools import (check_promotion, query_inventory,
                             report_repair, TOOL_SCHEMAS)


def test_report_repair_ok():
    r = report_repair("S001", "收银机", "开机黑屏")
    assert r["ok"] is True
    assert r["order_no"].startswith("RX")
    assert r["status"] == "已受理"


def test_report_repair_priority():
    r = report_repair("S001", "制冰机", "不出冰", priority="紧急")
    assert r["priority"] == "紧急"
    assert "2小时" in r["sla"]


def test_report_repair_invalid_store():
    r = report_repair("S999", "收银机", "故障")
    assert r["ok"] is False
    assert "无效门店" in r["error"]


def test_query_inventory_ok():
    r = query_inventory("S001", "可乐杯")
    assert r["ok"] is True
    assert r["material"] == "可乐杯"
    assert r["stock"] >= 0


def test_query_inventory_unknown():
    r = query_inventory("S001", "不存在的物料XYZ")
    assert r["ok"] is False


def test_check_promotion_ok():
    r = check_promotion("S001", "p01")   # 小写应被归一化
    assert r["ok"] is True
    assert r["policy_code"] == "P01"
    assert r["status"] == "生效中"


def test_check_promotion_expired():
    r = check_promotion("S001", "P99")
    assert r["ok"] is True
    assert r["status"] == "已过期"


def test_schemas_cover_tools():
    names = {s["name"] for s in TOOL_SCHEMAS}
    assert names == {"report_repair", "query_inventory", "check_promotion"}
    for s in TOOL_SCHEMAS:
        assert "required" in s["parameters"]
