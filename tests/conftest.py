"""pytest 共享夹具：临时门店文档语料 + 内存向量库。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根：E:\aa面试准备激素理解\project1_store_agent

from app.rag.vector_store import get_vector_store, reset_vector_store  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """每个测试用独立临时 SQLite，避免与运行中的服务抢 data/app.db。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from app import db
    db._conn = None
    db.init_db()

DOC_SAMPLES = [
    ("# 问题类别：设备报修：收银机死机处理\n"
     "## 操作步骤\n1. 长按电源键 10 秒强制重启\n2. 检查流水补传\n3. 提交报修工单\n"
     "## 注意事项\n- 重启前确认订单已打印\n- 严禁直接拔电源"),
    ("# 问题类别：物料库存：可乐杯库存管理\n"
     "## 操作步骤\n1. 每日晚班核对杯具库存\n2. 低于补货线 500 个时发起订货\n"
     "## 注意事项\n- 破损杯具单独存放\n- 订货周期 2 天"),
    ("# 问题类别：促销政策：会员日88折活动细则\n"
     "## 操作步骤\n1. 每周三会员全场 88 折\n2. 需出示会员码\n"
     "## 注意事项\n- 不与满减同享\n- 储值支付同样享受"),
]


@pytest.fixture()
def tiny_corpus(tmp_path):
    """构造 3 份测试文档并写入内存向量库。"""
    reset_vector_store()
    from app.rag.chunker import StructuredChunker
    from app.rag.embedder import embedder

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    for i, text in enumerate(DOC_SAMPLES):
        (docs_dir / f"doc{i}.md").write_text(text, encoding="utf-8")

    chunks = StructuredChunker(docs_dir).parse_dir()
    store, _ = get_vector_store(force="memory")
    store.clear()
    items = [{"id": c.chunk_id, "doc_id": c.doc_id, "category": c.category,
              "text": c.text, "metadata": {}} for c in chunks]
    store.add(items, embedder.embed([c.text for c in chunks]))
    return chunks, store
