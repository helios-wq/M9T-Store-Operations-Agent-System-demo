"""重排器：规则重排（关键词重叠 + 类别优先 + 位置加成）+ 可插拔 API 重排。

设计目标：召回 Top-10 → 精排 Top-3，提升 Top-3 命中率。
- 规则重排离线可用：融合向量分、查询词在文本中的命中率、类别匹配。
- APIReranker：在线时可用 bge-reranker 类交叉编码器（OpenAI 兼容接口），
  未配置 Key 时自动跳过，不影响主流程。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..config import settings


@dataclass
class RerankInput:
    chunk_id: str
    doc_id: str
    category: str
    text: str
    score: float          # 召回阶段融合分
    source: str = ""      # vector / keyword


def _tokenize(text: str) -> List[str]:
    """轻量分词：中文二元组 + 空白词。"""
    out = []
    chars = [c for c in text if c.strip()]
    out += ["".join(chars[i:i + 2]) for i in range(max(0, len(chars) - 1))]
    out += [w for w in text.split() if w]
    return out


def keyword_hit_rate(query: str, text: str) -> float:
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return 0.0
    t_tokens = set(_tokenize(text))
    hits = q_tokens & t_tokens
    return len(hits) / len(q_tokens)


class RuleReranker:
    """多因子融合重排：0.5*召回分 + 0.35*关键词命中 + 0.15*类别加分。"""

    def __init__(self, query_category: str | None = None):
        self.query_category = query_category or ""

    def rerank(self, query: str, items: List[RerankInput], top_k: int = 3) -> List[RerankInput]:
        scored = []
        for it in items:
            hit = keyword_hit_rate(query, it.text)
            cat_bonus = 0.15 if (self.query_category and self.query_category in it.category) else 0.0
            total = 0.5 * it.score + 0.35 * hit + cat_bonus
            scored.append((total, it))
        scored.sort(key=lambda x: -x[0])
        out = scored[:top_k]
        for s, it in out:
            it.score = round(s, 4)
        return [it for _, it in out]


class APIReranker:
    """在线交叉编码重排（如 SiliconFlow BAAI/bge-reranker-v2-m3）。
    未配置 Key 时返回 None 表示不可用。"""

    def __init__(self):
        self._client = None
        if settings.embed_api_key:  # 复用 Embedding 的 Key/BaseURL
            try:
                import httpx
                self._client = httpx.Client(timeout=30)
                self._base = settings.embed_base_url
                self._key = settings.embed_api_key
                self._model = "BAAI/bge-reranker-v2-m3"
            except Exception:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def rerank(self, query: str, texts: List[str]) -> List[float]:
        resp = self._client.post(
            f"{self._base}/rerank",
            json={"model": self._model, "query": query, "documents": texts, "top_n": len(texts)},
            headers={"Authorization": f"Bearer {self._key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        scores = [0.0] * len(texts)
        for item in data.get("results", []):
            scores[item["index"]] = item.get("relevance_score", 0.0)
        return scores


rule_reranker = RuleReranker()
api_reranker = APIReranker()


def rerank(query: str, items: List[RerankInput], top_k: int = 3,
           query_category: str | None = None) -> List[RerankInput]:
    """统一入口：在线优先 API 重排，否则规则重排。"""
    if api_reranker.available and len(items) > 1:
        try:
            scores = api_reranker.rerank(query, [it.text for it in items])
            ranked = sorted(zip(scores, items), key=lambda x: -x[0])[:top_k]
            for s, it in ranked:
                it.score = round(s, 4)
            return [it for _, it in ranked]
        except Exception:
            pass  # API 失败降级规则重排
    return RuleReranker(query_category).rerank(query, items, top_k)
