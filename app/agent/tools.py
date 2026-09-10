"""内部 API 工具集：设备报修 / 物料库存查询 / 促销政策校验。

每个工具 = 一个 Python 函数 + 一份 Function Calling JSON Schema，
供 ReAct 循环与离线规则路由共用。
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional

from ..config import settings
from ..wecom import send_wecom_message

STORE_IDS = [f"S{i:03d}" for i in range(1, 201)]           # 200+ 直营门店

# 物料库存（模拟数据；生产环境应接门店 ERP/供应链系统）
INVENTORY: Dict[str, dict] = {
    "可乐杯": {"stock": 1200, "unit": "个", "reorder": 500},
    "薯条袋": {"stock": 300, "unit": "个", "reorder": 600},
    "汉堡纸": {"stock": 2400, "unit": "张", "reorder": 800},
    "番茄酱包": {"stock": 1500, "unit": "包", "reorder": 700},
    "餐巾纸": {"stock": 200, "unit": "包", "reorder": 400},
    "冰激凌杯": {"stock": 800, "unit": "个", "reorder": 400},
    "打包袋": {"stock": 900, "unit": "个", "reorder": 500},
    "吸管": {"stock": 3500, "unit": "根", "reorder": 1500},
}

# 促销政策（模拟数据；生产环境接营销系统）
PROMOTIONS: Dict[str, dict] = {
    "P01": {"name": "全场满100减20", "rule": "单笔消费满100元立减20元", "status": "生效中", "valid_until": "2026-12-31"},
    "P02": {"name": "会员日88折", "rule": "每周三会员全场88折，不与满减同享", "status": "生效中", "valid_until": "2026-12-31"},
    "P03": {"name": "新品买一送一", "rule": "指定新品买一送一，仅限堂食", "status": "生效中", "valid_until": "2026-09-30"},
    "P04": {"name": "早餐时段优惠", "rule": "工作日7:00-9:00 早餐套餐立减5元", "status": "生效中", "valid_until": "2026-10-31"},
    "P99": {"name": "历史过期活动", "rule": "开业庆典全场五折（已结束）", "status": "已过期", "valid_until": "2026-01-31"},
}

# 设备类型
DEVICE_TYPES = ["收银机", "制冰机", "冷藏冰箱", "冷冻柜", "烤箱", "炸炉", "空调", "点餐屏", "打印机", "微波炉"]

# 主数据初始化标志（首次查询时自动把硬编码数据写入数据库）
_master_data_initialized = False


def _ensure_master_data() -> None:
    """首次运行时把硬编码的库存/促销/门店/设备主数据写入数据库。

    生产环境应通过 ERP/营销系统同步，这里保证零配置演示可用。
    已初始化后跳过（幂等）。
    """
    global _master_data_initialized
    if _master_data_initialized:
        return
    try:
        from ..db import upsert_inventory, upsert_promotion, upsert_store, list_inventory
        # 库存已有数据则不覆盖（生产环境已同步过）
        existing = list_inventory(limit=1)
        if not existing:
            for material, info in INVENTORY.items():
                # 给 S001 初始化一份演示数据，其他门店按需同步
                upsert_inventory("S001", material, info["stock"], info["unit"], info["reorder"])
        # 促销政策（全量初始化，可被管理接口覆盖）
        for code, p in PROMOTIONS.items():
            upsert_promotion(code, p["name"], p["rule"], p["status"], "", p["valid_until"])
        # 门店主数据（S001-S010 初始化演示，其余按需扩展）
        for i in range(1, 11):
            sid = f"S{i:03d}"
            upsert_store(sid, f"{sid} 直营门店", f"上海市演示区路{i}号", f"021-0000{i:04d}", f"店长{i}", "营业中")
        _master_data_initialized = True
    except Exception as e:  # pragma: no cover
        print(f"[tools] 主数据初始化失败（将使用硬编码 fallback）：{e}")


def _normalize_store(store_id: str) -> str:
    """S80 → S080；容忍用户输入格式差异。"""
    m = re.match(r"^[Ss](\d{1,3})$", (store_id or "").strip())
    if m:
        return f"S{int(m.group(1)):03d}"
    return (store_id or "").strip().upper()


def _validate_store(store_id: str) -> Optional[str]:
    sid = _normalize_store(store_id)
    if sid not in STORE_IDS:
        return f"无效门店编号 {store_id}，请输入 S001-S200 之间的编号"
    return None


# ---------------------------------------------------------------- 企微推送
def _push_wecom(text: str) -> None:
    """推送企微消息（配置了 WECOM_WEBHOOK 才推，未配置静默跳过）。"""
    if settings.wecom_webhook:
        send_wecom_message(settings.wecom_webhook, text)


def notify_repair_dispatched(record: dict) -> Optional[str]:
    """工单推进到「已派单」后推送维修群（通知维修组接单处理）。

    失败不抛异常，返回错误信息供调用方记录；未配置 webhook 静默跳过。
    """
    try:
        _push_wecom(
            f"📋 工单 {record['order_no']} 已派单\n"
            f"门店 {record['store_id']}｜设备 {record['device']}\n"
            f"故障：{record.get('problem_desc', '')}\n"
            f"优先级：{record.get('priority', '普通')}｜{record.get('sla', '')}\n"
            f"维修组请尽快处理",
        )
        return None
    except Exception as e:  # pragma: no cover
        return str(e)


# ---------------------------------------------------------------- 工具 1
def report_repair(store_id: str, device: str, problem_desc: str, priority: str = "普通") -> dict:
    """设备报修：创建维修工单并返回单号与响应时效。"""
    err = _validate_store(store_id)
    if err:
        return {"ok": False, "error": err}
    device = device.strip()
    if not device:
        return {"ok": False, "error": "请提供需要报修的设备名称"}
    priority = priority if priority in ("紧急", "普通") else "普通"
    # 纳秒级时间戳保证单号唯一（秒级会在高并发/测试同秒内撞号）
    order_no = f"RX{time.time_ns() % 100000000:08d}"
    sla = "2小时内响应" if priority == "紧急" else "24小时内响应"
    record = {
        "order_no": order_no, "store_id": store_id, "device": device,
        "problem_desc": problem_desc, "priority": priority, "status": "已受理", "sla": sla,
    }
    # 持久化到业务库（MySQL，连不上自动降级 SQLite）
    try:
        from ..db import repair_store
        repair_store(record)
    except Exception as e:  # pragma: no cover
        record["persist_error"] = str(e)
    # 推送到企微维修群（配置了 WECOM_WEBHOOK 才推，未配置静默跳过）
    try:
        _push_wecom(
            f"🔧 新报修工单\n单号 {order_no}｜门店 {store_id}｜设备 {device}\n"
            f"故障：{problem_desc}\n优先级：{priority}｜{sla}\n请维修组接单并回复「{order_no} 已派单」",
        )
    except Exception as e:  # pragma: no cover
        record["notify_error"] = str(e)
    return {"ok": True, **record}


# ---------------------------------------------------------------- 工具 2
def query_inventory(store_id: str, material: str) -> dict:
    """物料库存查询：返回指定物料库存与补货建议。

    优先从数据库查询（支持 ERP 实时同步）；数据库无数据时回退硬编码模拟数据。
    """
    err = _validate_store(store_id)
    if err:
        return {"ok": False, "error": err}
    _ensure_master_data()
    material = material.strip()
    # 优先从数据库查询
    try:
        from ..db import get_inventory, list_inventory
        # 精确匹配
        record = get_inventory(store_id, material)
        if not record:
            # 模糊匹配：遍历该门店所有物料，找包含关系
            all_items = list_inventory(store_id=store_id, limit=200)
            for item in all_items:
                if material in item["material"] or item["material"] in material:
                    record = item
                    break
        if record:
            stock = int(record["stock"])
            reorder = int(record.get("reorder_point", 0))
            return {
                "ok": True, "store_id": store_id, "material": record["material"],
                "stock": stock, "unit": record.get("unit", "个"), "reorder_point": reorder,
                "suggestion": "建议补货" if stock < reorder else "库存充足",
            }
    except Exception as e:  # pragma: no cover
        print(f"[tools] 数据库库存查询失败，回退硬编码：{e}")
    # 回退：硬编码模拟数据（门店间小幅度浮动）
    seed = sum(ord(c) for c in store_id)
    for name, info in INVENTORY.items():
        if name in material or material in name or material == "":
            stock = max(0, info["stock"] + (seed % 5 - 2) * 10)
            return {
                "ok": True, "store_id": store_id, "material": name,
                "stock": stock, "unit": info["unit"], "reorder_point": info["reorder"],
                "suggestion": "建议补货" if stock < info["reorder"] else "库存充足",
            }
    return {"ok": False, "error": f"未找到物料「{material}」，请检查名称（如：可乐杯/薯条袋/番茄酱包）"}


# ---------------------------------------------------------------- 工具 3
def check_promotion(store_id: str, policy_code: str) -> dict:
    """促销政策校验：核对政策编号是否生效及规则详情。

    优先从数据库查询（支持动态管理）；数据库无数据时回退硬编码模拟数据。
    """
    err = _validate_store(store_id)
    if err:
        return {"ok": False, "error": err}
    _ensure_master_data()
    code = policy_code.strip().upper()
    # 优先从数据库查询
    try:
        from ..db import get_promotion
        record = get_promotion(code)
        if record:
            return {
                "ok": True, "store_id": store_id, "policy_code": code,
                "policy_name": record["name"], "rule": record["rule"],
                "status": record["status"], "valid_until": record.get("valid_until", ""),
            }
    except Exception as e:  # pragma: no cover
        print(f"[tools] 数据库促销查询失败，回退硬编码：{e}")
    # 回退：硬编码模拟数据
    if code not in PROMOTIONS:
        return {"ok": False, "error": f"未找到政策编号 {code}，可用编号：{', '.join(sorted(PROMOTIONS))}"}
    p = PROMOTIONS[code]
    return {
        "ok": True, "store_id": store_id, "policy_code": code, "policy_name": p["name"],
        "rule": p["rule"], "status": p["status"], "valid_until": p["valid_until"],
    }


# ---------------------------------------------------------------- 注册表
TOOL_FUNCTIONS: Dict[str, callable] = {
    "report_repair": report_repair,
    "query_inventory": query_inventory,
    "check_promotion": check_promotion,
}

TOOL_SCHEMAS: List[dict] = [
    {
        "name": "report_repair",
        "description": "提交设备报修工单。当店长/店员报告设备故障、损坏、无法使用时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string", "description": "门店编号，如 S001"},
                "device": {"type": "string", "description": "设备名称，如 收银机"},
                "problem_desc": {"type": "string", "description": "故障现象描述"},
                "priority": {"type": "string", "enum": ["紧急", "普通"], "description": "紧急程度，默认普通"},
            },
            "required": ["store_id", "device", "problem_desc"],
        },
    },
    {
        "name": "query_inventory",
        "description": "查询门店物料库存。当询问物料/库存/还有多少时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string", "description": "门店编号"},
                "material": {"type": "string", "description": "物料名称，如 可乐杯"},
            },
            "required": ["store_id", "material"],
        },
    },
    {
        "name": "check_promotion",
        "description": "校验促销政策是否生效及规则。当询问促销/活动/优惠/折扣政策时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string", "description": "门店编号"},
                "policy_code": {"type": "string", "description": "政策编号，如 P01"},
            },
            "required": ["store_id", "policy_code"],
        },
    },
]


# 工具与问题类别/意图的映射（离线路由用）
TOOL_INTENT_MAP = {
    "repair_tool": "report_repair",
    "inventory_tool": "query_inventory",
    "promotion_tool": "check_promotion",
}

# 工具到问题类别的映射（工具失败降级检索时的过滤类别）
TOOL_CATEGORY_MAP = {
    "report_repair": "设备报修",
    "query_inventory": "物料库存",
    "check_promotion": "促销政策",
}
