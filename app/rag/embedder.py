"""Embedding 封装：OpenAI 兼容 API（bge-m3 等）+ 离线哈希向量双模式。

offline（未配置 EMBED_API_KEY）时使用「字符二元组特征哈希 + L2 归一化」，
在同一份语料/查询上能给出可用的语义相似度排序，保证零配置可演示。
"""
from __future__ import annotations

import hashlib
import math
from typing import List

from ..config import settings


def _feature_hasher(text: str, dim: int) -> List[float]:
    vec = [0.0] * dim
    # 中文二元组 + 英文词袋
    tokens: List[str] = []
    chars = [c for c in text if c.strip()]
    tokens += ["".join(chars[i:i + 2]) for i in range(len(chars) - 1)]
    tokens += [w for w in text.replace("，", " ").replace("。", " ").replace("、", " ").split() if w and len(w) > 1]
    for t in tokens:
        h = int(hashlib.md5(t.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Embedder:
    def __init__(self):
        self.dim = settings.embed_dim
        self._client = None
        if settings.embed_api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=settings.embed_api_key, base_url=settings.embed_base_url, timeout=60)
            except Exception:
                self._client = None

    @property
    def offline(self) -> bool:
        return self._client is None

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self.offline:
            return [_feature_hasher(t, self.dim) for t in texts]
        resp = self._client.embeddings.create(model=settings.embed_model, input=texts)
        # 兼容排序
        data = sorted(resp.data, key=lambda x: x.index)
        return [d.embedding for d in data]

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]


embedder = Embedder()
