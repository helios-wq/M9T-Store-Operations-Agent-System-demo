"""主数据管理测试：库存 / 促销 / 门店 / 设备 / 员工 CRUD。"""
from __future__ import annotations

import pytest

from app.db import (
    init_db, upsert_inventory, get_inventory, list_inventory, update_inventory_stock,
    upsert_promotion, get_promotion, list_promotions,
    upsert_store, get_store, list_stores,
    upsert_device, get_device, list_devices,
    upsert_staff, get_staff, list_staff,
)


@pytest.fixture(autouse=True)
def _setup_db():
    """每个测试用独立临时库（conftest 已通过 DB_PATH 环境变量隔离）。"""
    init_db()
    yield


# ---------------- 库存测试 ----------------
class TestInventory:
    def test_upsert_and_get(self):
        upsert_inventory("S001", "可乐杯", 1000, "个", 500)
        record = get_inventory("S001", "可乐杯")
        assert record is not None
        assert record["store_id"] == "S001"
        assert record["material"] == "可乐杯"
        assert record["stock"] == 1000
        assert record["unit"] == "个"
        assert record["reorder_point"] == 500

    def test_upsert_update_existing(self):
        upsert_inventory("S001", "可乐杯", 1000, "个", 500)
        upsert_inventory("S001", "可乐杯", 800, "个", 600)  # 更新
        record = get_inventory("S001", "可乐杯")
        assert record["stock"] == 800
        assert record["reorder_point"] == 600

    def test_list_by_store(self):
        upsert_inventory("S001", "可乐杯", 1000, "个", 500)
        upsert_inventory("S001", "薯条袋", 300, "个", 600)
        upsert_inventory("S002", "可乐杯", 500, "个", 500)
        items = list_inventory(store_id="S001")
        assert len(items) == 2
        materials = {i["material"] for i in items}
        assert materials == {"可乐杯", "薯条袋"}

    def test_update_stock_delta(self):
        upsert_inventory("S001", "可乐杯", 1000, "个", 500)
        result = update_inventory_stock("S001", "可乐杯", -100)
        assert result is not None
        assert result["stock"] == 900
        # 入库
        result = update_inventory_stock("S001", "可乐杯", 200)
        assert result["stock"] == 1100

    def test_update_stock_not_negative(self):
        upsert_inventory("S001", "可乐杯", 50, "个", 500)
        result = update_inventory_stock("S001", "可乐杯", -100)
        assert result["stock"] == 0  # 不能为负

    def test_get_nonexistent(self):
        assert get_inventory("S999", "不存在") is None


# ---------------- 促销测试 ----------------
class TestPromotion:
    def test_upsert_and_get(self):
        upsert_promotion("P01", "全场满100减20", "单笔满100减20", "生效中", "", "2026-12-31")
        record = get_promotion("P01")
        assert record is not None
        assert record["promo_code"] == "P01"
        assert record["name"] == "全场满100减20"
        assert record["status"] == "生效中"

    def test_list_by_status(self):
        upsert_promotion("P01", "活动1", "规则1", "生效中", "", "2026-12-31")
        upsert_promotion("P02", "活动2", "规则2", "已过期", "", "2026-01-01")
        active = list_promotions(status="生效中")
        assert len(active) == 1
        assert active[0]["promo_code"] == "P01"


# ---------------- 门店测试 ----------------
class TestStore:
    def test_upsert_and_get(self):
        upsert_store("S001", "S001 直营门店", "上海市路1号", "021-0001", "店长1", "营业中")
        record = get_store("S001")
        assert record is not None
        assert record["store_id"] == "S001"
        assert record["name"] == "S001 直营门店"
        assert record["status"] == "营业中"

    def test_list_all(self):
        upsert_store("S001", "门店1", "", "", "", "营业中")
        upsert_store("S002", "门店2", "", "", "", "停业")
        all_stores = list_stores()
        assert len(all_stores) == 2


# ---------------- 设备测试 ----------------
class TestDevice:
    def test_upsert_and_get(self):
        upsert_device("D001", "S001", "收银机", "品牌A", "型号X", "2025-01-01", "2028-01-01", "正常")
        record = get_device("D001")
        assert record is not None
        assert record["device_id"] == "D001"
        assert record["store_id"] == "S001"
        assert record["device_type"] == "收银机"

    def test_list_by_store(self):
        upsert_device("D001", "S001", "收银机", "", "", "", "", "正常")
        upsert_device("D002", "S001", "制冰机", "", "", "", "", "正常")
        upsert_device("D003", "S002", "收银机", "", "", "", "", "正常")
        devices = list_devices(store_id="S001")
        assert len(devices) == 2


# ---------------- 员工测试 ----------------
class TestStaff:
    def test_upsert_and_get(self):
        upsert_staff("E001", "张三", "店长", "13800000001", "S001", "在职")
        record = get_staff("E001")
        assert record is not None
        assert record["staff_id"] == "E001"
        assert record["name"] == "张三"
        assert record["role"] == "店长"

    def test_list_by_role(self):
        upsert_staff("E001", "张三", "店长", "", "S001", "在职")
        upsert_staff("E002", "李四", "店员", "", "S001", "在职")
        upsert_staff("E003", "王五", "维修工", "", "S001", "在职")
        managers = list_staff(role="店长")
        assert len(managers) == 1
        assert managers[0]["name"] == "张三"
