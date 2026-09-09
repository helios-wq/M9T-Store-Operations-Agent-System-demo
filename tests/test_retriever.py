"""多路检索器单测（内存向量库 + 离线哈希向量）。"""
from app.rag.retriever import Retriever


def test_retrieve_top1_matches_category(tiny_corpus):
    retriever = Retriever()
    results = retriever.retrieve("收银机死机了怎么处理", top_k=3)
    assert len(results) >= 1
    assert results[0].doc_id == "doc0"       # 设备报修文档应排第一


def test_retrieve_synonym_expansion(tiny_corpus):
    retriever = Retriever()
    # "还有多少" 命中库存语义，应检索到 doc1
    results = retriever.retrieve("我们店可乐杯还有多少", top_k=3)
    doc_ids = {r.doc_id for r in results}
    assert "doc1" in doc_ids


def test_retrieve_promotion(tiny_corpus):
    retriever = Retriever()
    results = retriever.retrieve("会员日打88折是什么活动", top_k=3)
    assert results[0].doc_id == "doc2"


def test_retrieve_empty_corpus(tmp_path):
    from app.rag.chunker import StructuredChunker
    from app.rag.embedder import embedder
    from app.rag.vector_store import get_vector_store, reset_vector_store
    reset_vector_store()
    docs_dir = tmp_path / "empty"
    docs_dir.mkdir()
    chunks = StructuredChunker(docs_dir).parse_dir()
    store, _ = get_vector_store(force="memory")
    store.clear()
    store.add([], [])
    retriever = Retriever()
    assert retriever.retrieve("随便问问", top_k=3) == []
