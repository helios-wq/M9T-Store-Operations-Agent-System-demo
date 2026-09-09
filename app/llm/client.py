"""LLM 客户端：OpenAI 兼容协议（DeepSeek 等）。

核心设计：
1. 无 API Key 时自动进入 offline 模式 —— 全部方法返回规则化结果，
   保证"零配置"也能跑通 Agent 全流程，便于本地演示与单测。
2. chat / stream / json 三类调用统一封装，业务层不感知底层 SDK。
"""
from __future__ import annotations

import json
import re
from typing import AsyncGenerator, List

from ..config import settings


def _canned_reply() -> str:
    return "【离线演示】未配置 LLM_API_KEY，当前为规则引擎回复。请配置 Key 后获得完整大模型回答。"


class LLMClient:
    def __init__(self):
        self._client = None
        self._async_client = None
        if settings.llm_api_key:
            try:
                from openai import AsyncOpenAI, OpenAI
                common = dict(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=60)
                self._client = OpenAI(**common)
                self._async_client = AsyncOpenAI(**common)
            except Exception:
                self._client = None

    @property
    def offline(self) -> bool:
        return self._client is None

    # ---------------- 同步 ----------------
    def chat(self, messages: List[dict], temperature: float | None = None,
             max_tokens: int | None = None, json_mode: bool = False) -> str:
        if self.offline:
            return _canned_reply()
        kwargs = dict(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature if temperature is None else temperature,
        )
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def extract_json(self, messages: List[dict], max_retries: int = 2) -> dict:
        """要求模型返回 JSON 对象，带重试与容错解析。"""
        prompt = ("请只输出一个合法的 JSON 对象，不要输出任何其他文字、注释或 Markdown 代码块。")
        msgs = list(messages) + [{"role": "user", "content": prompt}]
        for _ in range(max_retries + 1):
            raw = self.chat(msgs, temperature=0.1, json_mode=True)
            obj = self._parse_json(raw)
            if obj is not None:
                return obj
        return {}

    # ---------------- 异步 ----------------
    async def achat(self, messages: List[dict], temperature: float | None = None,
                    max_tokens: int | None = None, json_mode: bool = False) -> str:
        if self.offline:
            return _canned_reply()
        kwargs = dict(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature if temperature is None else temperature,
        )
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._async_client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    async def achat_stream(self, messages: List[dict], temperature: float | None = None) -> AsyncGenerator[str, None]:
        """流式返回文本增量。offline 模式一次性吐回整句。"""
        if self.offline:
            yield _canned_reply()
            return
        kwargs = dict(
            model=settings.llm_model,
            messages=messages,
            stream=True,
            temperature=settings.llm_temperature if temperature is None else temperature,
        )
        stream = await self._async_client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def aextract_json(self, messages: List[dict], max_retries: int = 2) -> dict:
        prompt = ("请只输出一个合法的 JSON 对象，不要输出任何其他文字、注释或 Markdown 代码块。")
        msgs = list(messages) + [{"role": "user", "content": prompt}]
        for _ in range(max_retries + 1):
            raw = await self.achat(msgs, temperature=0.1, json_mode=True)
            obj = self._parse_json(raw)
            if obj is not None:
                return obj
        return {}

    # ---------------- 工具 ----------------
    @staticmethod
    def _parse_json(raw: str):
        if not raw:
            return None
        text = raw.strip()
        # 去掉 ```json ... ``` 包裹
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        # 尝试截取第一个 { 到最后一个 }
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                return None
        return None


llm_client = LLMClient()
