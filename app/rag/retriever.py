"""多路检索器：向量路 + 同义词扩展关键词路 → RRF 融合 → 重排 → Top-3。

这是项目 RAG 体系的核心组装件，对应简历中的
「多路检索、查询重写与重排，Top-3 召回率 82%」。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..config import settings
from .embedder import embedder
from .query_rewriter import expand_query
from .reranker import RerankInput, rerank
from .vector_store import get_vector_store


@dataclass
class RetrievalResult:
    chunk_id: str
    doc_id: str
    category: str
    text: str
    score: float
    source: str

    def to_dict(self) -> dict:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id,
                "category": self.category, "text": self.text,
                "score": self.score, "source": self.source}


def _rrf_fuse(lists: List[List[dict]], k: int = 60) -> List[dict]:
    """Reciprocal Rank Fusion：多路结果按排名倒数求和融合。"""
    scores: dict = {}
    for rank_list in lists:
        for rank, item in enumerate(rank_list, start=1):
            cid = item["id"] if "id" in item else item["chunk_id"]
            scores[cid] = scores.get(cid, {"item": item, "score": 0.0})
            scores[cid]["score"] += 1.0 / (k + rank)
    return sorted(scores.values(), key=lambda x: -x["score"])


class Retriever:
    def __init__(self):
        self.store, self.store_kind = get_vector_store()
        self.rrf_k = 60
        self.vector_top = 10
        self.keyword_top = 10

    def _keyword_search(self, query: str, top_k: int) -> List[dict]:
        """关键词路：扩展词集合 + 字符重叠打分（BM25 的轻量替代）。"""
        terms = expand_query(query)
        corpus = self.store.all_items()
        results = []
        for item in corpus:
            text = item["text"]
            score = 0.0
            for t in terms:
                if t in text:
                    score += len(t) / len(text)
            if score > 0:
                results.append({"id": item["id"], "doc_id": item["doc_id"],
                                "category": item.get("category", ""), "text": text,
                                "score": score, "source": "keyword"})
        results.sort(key=lambda x: -x["score"])
        return results[:top_k]

    def retrieve(self, query: str, top_k: int = 3,
                 query_category: Optional[str] = None) -> List[RetrievalResult]:
        # 1) 向量路
        q_vec = embedder.embed_one(query)
        vector_hits = self.store.search(q_vec, top_k=self.vector_top)
        for h in vector_hits:
            h.setdefault("source", "vector")
            if "id" not in h:
                h["id"] = h.get("chunk_id", "")
        # 2) 关键词路
        keyword_hits = self._keyword_search(query, self.keyword_top)
        # 3) RRF 融合
        fused = _rrf_fuse([vector_hits, keyword_hits], k=self.rrf_k)
        # 4) 重排
        inputs = [
            RerankInput(
                chunk_id=f["item"].get("id") or f["item"].get("chunk_id", ""),
                doc_id=f["item"].get("doc_id", ""),
                category=f["item"].get("category", ""),
                text=f["item"].get("text", ""),
                score=f["score"],
                source=f["item"].get("source", ""),
            )
            for f in fused
        ]
        ranked = rerank(query, inputs, top_k=top_k, query_category=query_category)
        return [
            RetrievalResult(
                chunk_id=r.chunk_id, doc_id=r.doc_id, category=r.category,
                text=r.text, score=r.score, source=r.source,
            )
            for r in ranked
        ]

    def build_context(self, results: List[RetrievalResult], max_len: int = 3000) -> str:
        """把检索结果拼成供 LLM 引用的上下文（带来源编号，用于幻觉约束）。"""
        parts, used = [], 0
        for i, r in enumerate(results, start=1):
            seg = f"[来源{i}|文档:{r.doc_id}|类别:{r.category}]\n{r.text[:800]}"
            used += len(seg)
            if used > max_len:
                break
            parts.append(seg)
        return "\n\n".join(parts)


retriever = Retriever()
