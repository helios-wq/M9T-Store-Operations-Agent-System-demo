"""构建 RAG 索引：文档 → 结构化分块 → 向量化 → 入库（Milvus/内存）→ 持久化。

用法：python scripts/build_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings                      # noqa: E402
from app.rag.chunker import chunk_documents           # noqa: E402
from app.rag.embedder import embedder                 # noqa: E402
from app.rag.vector_store import get_vector_store     # noqa: E402


def main() -> None:
    print("1) 解析门店文档（结构化分块）...")
    chunks = chunk_documents()
    if not chunks:
        print("未找到文档，请先运行：python data/gen_docs.py")
        return
    print(f"   → 共 {len(chunks)} 个 Chunk")

    print("2) 向量化...")
    texts = [c.text for c in chunks]
    vectors = embedder.embed(texts)
    print(f"   → 向量维度 {len(vectors[0])}，模式：{'离线哈希' if embedder.offline else 'API'}")

    print("3) 写入向量库...")
    store, kind = get_vector_store(force="auto")
    store.clear()
    items = [
        {
            "id": c.chunk_id,
            "doc_id": c.doc_id,
            "category": c.category,
            "text": c.text,
            "metadata": {"keywords": c.keywords, "steps": c.steps, "notices": c.notices},
        }
        for c in chunks
    ]
    store.add(items, vectors)
    if kind == "memory":
        store.save(settings.index_path)
        print(f"   → 已持久化到 {settings.index_path}")
    print(f"索引构建完成：{store.count()} 条 Chunk → {kind} 存储")


if __name__ == "__main__":
    main()
