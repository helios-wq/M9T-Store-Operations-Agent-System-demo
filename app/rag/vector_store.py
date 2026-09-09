"""向量存储：Milvus 生产实现 + 内存向量库降级，工厂方法自动选择。

统一接口：add / search / count / all_items / save / load / clear
- MemoryVectorStore：numpy 余弦相似度，可持久化到 data/index.json，
  零依赖即可跑通「文档→分块→向量化→入库→检索」全链路。
- MilvusVectorStore：pymilvus 集合 store_chunks（字段：id/doc_id/category/text/metadata/vector）。
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

import numpy as np

from ..config import settings


class MemoryVectorStore:
    def __init__(self):
        self.items: List[dict] = []          # {"id","doc_id","category","text","metadata"}
        self.vectors: np.ndarray = np.zeros((0, settings.embed_dim), dtype=np.float32)

    def add(self, items: List[dict], vectors: List[List[float]]) -> None:
        for it, v in zip(items, vectors):
            self.items.append(it)
        self.vectors = np.vstack([self.vectors, np.asarray(vectors, dtype=np.float32)]) if len(vectors) else self.vectors

    def search(self, vector: List[float], top_k: int = 3) -> List[dict]:
        if not self.items:
            return []
        q = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        sims = (self.vectors @ q.T).flatten()
        idx = np.argsort(-sims)[:top_k]
        return [
            {**self.items[i], "score": float(sims[i])}
            for i in idx if sims[i] > 0
        ]

    def all_items(self, limit: int = 50000) -> List[dict]:
        return self.items[:limit]

    def count(self) -> int:
        return len(self.items)

    def save(self, path) -> None:
        path = str(path)
        payload = {"items": self.items, "vectors": self.vectors.tolist()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    def load(self, path) -> None:
        path = str(path)
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self.items = payload["items"]
        self.vectors = np.asarray(payload["vectors"], dtype=np.float32)

    def clear(self) -> None:
        self.items = []
        self.vectors = np.zeros((0, settings.embed_dim), dtype=np.float32)


class MilvusVectorStore:
    COLLECTION = "store_chunks"

    def __init__(self, host: str = None, port: int = None):
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
        self._pymilvus = __import__("pymilvus")
        connections.connect(alias="default", host=host or settings.milvus_host, port=port or settings.milvus_port)
        if utility.has_collection(self.COLLECTION):
            self.col = Collection(self.COLLECTION)
        else:
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="metadata", dtype=DataType.JSON),
                FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=settings.embed_dim),
            ]
            schema = CollectionSchema(fields, description="store knowledge chunks")
            self.col = Collection(self.COLLECTION, schema=schema)
            index = {"index_type": "IVF_FLAT", "metric_type": "IP", "params": {"nlist": 128}}
            self.col.create_index("vector", index)
        self.col.load()

    def add(self, items: List[dict], vectors: List[List[float]]) -> None:
        data = [
            [it["id"] for it in items],
            [it["doc_id"] for it in items],
            [it.get("category", "") for it in items],
            [it["text"] for it in items],
            [it.get("metadata", {}) for it in items],
            [list(map(float, v)) for v in vectors],
        ]
        self.col.insert(data)
        self.col.flush()

    def search(self, vector: List[float], top_k: int = 3) -> List[dict]:
        res = self.col.search(
            data=[list(vector)], anns_field="vector",
            param={"metric_type": "IP", "params": {"nprobe": 16}},
            limit=top_k, output_fields=["id", "doc_id", "category", "text", "metadata"],
        )
        out = []
        for hit in res[0]:
            out.append({
                "id": hit.entity.get("id"),
                "doc_id": hit.entity.get("doc_id"),
                "category": hit.entity.get("category"),
                "text": hit.entity.get("text"),
                "metadata": hit.entity.get("metadata") or {},
                "score": float(hit.score),
            })
        return out

    def all_items(self, limit: int = 50000) -> List[dict]:
        res = self.col.query(expr=f"id != ''", output_fields=["id", "doc_id", "category", "text", "metadata"], limit=limit)
        return [{"id": r["id"], "doc_id": r["doc_id"], "category": r["category"], "text": r["text"], "metadata": r["metadata"]} for r in res]

    def count(self) -> int:
        return self.col.num_entities

    def clear(self) -> None:
        self.col.delete(expr=f"id != ''")
        self.col.flush()

    def save(self, path) -> None:   # Milvus 数据在服务端，无需本地持久化
        pass

    def load(self, path) -> None:
        pass


_store: Optional[object] = None
_store_kind: str = "memory"


def get_vector_store(force: str = "auto"):
    """工厂：auto = 优先 Milvus（连不上自动降级内存库）；memory/milvus 强制指定。"""
    global _store, _store_kind
    if _store is not None and force == "auto":
        return _store, _store_kind
    if force == "milvus" or (force == "auto" and settings.milvus_host):
        try:
            _store = MilvusVectorStore()
            _store_kind = "milvus"
            return _store, _store_kind
        except Exception:
            if force == "milvus":
                raise
            print("[vector_store] Milvus 连接失败，降级为内存向量库")
    _store = MemoryVectorStore()
    _store_kind = "memory"
    # 自动加载本地持久化索引（build_index.py 产物），保证脚本/评测/服务一致性
    try:
        if settings.index_path.exists():
            _store.load(settings.index_path)
    except Exception as e:
        print(f"[vector_store] 索引加载失败（{e}），请重新运行 scripts/build_index.py")
    return _store, _store_kind


def reset_vector_store() -> None:
    global _store
    _store = None
