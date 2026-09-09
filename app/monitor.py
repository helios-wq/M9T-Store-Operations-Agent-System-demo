"""监控告警：延迟/错误率指标采集 + 飞书群机器人告警 + /metrics 暴露。

设计：
- MetricsCollector 进程内维护计数（请求数/错误数/延迟分布），线程安全；
- 每次请求由接口层调用 record()；
- check_alert() 在窗口内错误率或 P95 延迟超阈值时触发飞书告警（带冷却期，避免刷屏）；
- /metrics 以 Prometheus 文本格式输出。
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import httpx

from .config import settings


class MetricsCollector:
    def __init__(self, window_sec: int = 300):
        self.window_sec = window_sec
        self._lock = threading.Lock()
        self._requests: list = []      # (ts, latency_ms, is_error)
        self._last_alert_at = 0.0

    def record(self, latency_ms: float, is_error: bool = False) -> None:
        with self._lock:
            now = time.time()
            self._requests = [(ts, l, e) for ts, l, e in self._requests if now - ts <= self.window_sec]
            self._requests.append((now, latency_ms, is_error))

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            items = [(ts, l, e) for ts, l, e in self._requests if now - ts <= self.window_sec]
        if not items:
            return {"total": 0, "errors": 0, "error_rate": 0.0, "avg_latency_ms": 0.0,
                    "p95_latency_ms": 0.0, "window_sec": self.window_sec}
        lats = sorted(l for _, l, _ in items)
        p95 = lats[min(len(lats) - 1, int(len(lats) * 0.95))]
        return {
            "total": len(items),
            "errors": sum(1 for _, _, e in items if e),
            "error_rate": sum(1 for _, _, e in items if e) / len(items),
            "avg_latency_ms": round(sum(lats) / len(lats), 1),
            "p95_latency_ms": round(p95, 1),
            "window_sec": self.window_sec,
        }

    def check_alert(self, force: bool = False) -> Optional[str]:
        """窗口内错误率/延迟超阈值 → 发飞书告警（冷却 10 分钟）。"""
        if not settings.feishu_webhook:
            return None
        snap = self.snapshot()
        if snap["total"] < 5:      # 样本太少不告警
            return None
        reasons = []
        if snap["error_rate"] >= settings.alert_error_rate:
            reasons.append(f"错误率 {snap['error_rate']:.1%} ≥ {settings.alert_error_rate:.0%}")
        if snap["p95_latency_ms"] >= settings.alert_latency_ms:
            reasons.append(f"P95 延迟 {snap['p95_latency_ms']}ms ≥ {settings.alert_latency_ms}ms")
        if not reasons:
            return None
        with self._lock:
            now = time.time()
            if now - self._last_alert_at < 600:
                return None
            self._last_alert_at = now
        text = (f"🔔 门店助手服务告警\n{'；'.join(reasons)}\n"
                f"近{snap['window_sec'] // 60}分钟：请求 {snap['total']}，错误 {snap['errors']}，"
                f"平均延迟 {snap['avg_latency_ms']}ms")
        try:
            httpx.post(settings.feishu_webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        except Exception:
            pass
        return text

    def prometheus_text(self) -> str:
        snap = self.snapshot()
        return (
            "# HELP store_agent_requests_total 请求总数\n"
            "# TYPE store_agent_requests_total counter\n"
            f"store_agent_requests_total {snap['total']}\n"
            "# HELP store_agent_errors_total 错误总数\n"
            f"store_agent_errors_total {snap['errors']}\n"
            "# HELP store_agent_avg_latency_ms 平均延迟\n"
            f"store_agent_avg_latency_ms {snap['avg_latency_ms']}\n"
            "# HELP store_agent_p95_latency_ms P95延迟\n"
            f"store_agent_p95_latency_ms {snap['p95_latency_ms']}\n"
        )


metrics = MetricsCollector()
