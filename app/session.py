"""会话管理：Redis 缓存 Agent 状态（自动降级内存实现）。

会话状态以 JSON 存于 Redis Hash（key: agent:session:{sid}），TTL 默认 2 小时。
Redis 不可用时自动切换到进程内内存存储，保证单机演示可跑。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Optional

from .config import settings


class SessionStore:
    def __init__(self):
        self._redis = None
        self._memory: dict = {}
        self._lock = threading.Lock()
        try:
            import redis
            self._redis = redis.Redis(
                host=settings.redis_host, port=settings.redis_port,
                db=settings.redis_db, socket_connect_timeout=1, decode_responses=True,
            )
            self._redis.ping()
        except Exception:
            self._redis = None
            print("[session] Redis 连接失败，降级为内存会话存储")

    @property
    def backend(self) -> str:
        return "redis" if self._redis else "memory"

    def new_session(self) -> str:
        return uuid.uuid4().hex[:16]

    def get(self, session_id: str) -> Optional[dict]:
        key = f"agent:session:{session_id}"
        if self._redis:
            raw = self._redis.get(key)
            return json.loads(raw) if raw else None
        with self._lock:
            item = self._memory.get(key)
            if not item:
                return None
            if item["expire_at"] < time.time():
                self._memory.pop(key, None)
                return None
            return item["data"]

    def set(self, session_id: str, state: dict, ttl: int = 7200) -> None:
        key = f"agent:session:{session_id}"
        raw = json.dumps(state, ensure_ascii=False)
        if self._redis:
            self._redis.set(key, raw, ex=ttl)
            return
        with self._lock:
            self._memory[key] = {"data": state, "expire_at": time.time() + ttl}

    def delete(self, session_id: str) -> None:
        key = f"agent:session:{session_id}"
        if self._redis:
            self._redis.delete(key)
            return
        with self._lock:
            self._memory.pop(key, None)


session_store = SessionStore()
