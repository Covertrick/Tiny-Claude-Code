"""全局令牌桶限流 + 风控熔断（防 QQ 高频规律发送）。"""

from __future__ import annotations

import random
import threading
import time
from typing import Any


class TokenBucket:
    """经典令牌桶：capacity 最大突发，refill_rate 每秒补充令牌数。"""

    def __init__(self, *, capacity: float = 5.0, refill_rate: float = 0.8):
        self.capacity = max(1.0, float(capacity))
        self.refill_rate = max(0.05, float(refill_rate))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)

    def acquire(self, tokens: float = 1.0, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                need = tokens - self._tokens
                wait = need / self.refill_rate
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.5))


class SendCircuitBreaker:
    """连续风控失败后熔断一段时间，只允许降级/告警。"""

    def __init__(self, *, fail_threshold: int = 3, cool_seconds: float = 120.0):
        self.fail_threshold = max(1, fail_threshold)
        self.cool_seconds = max(10.0, cool_seconds)
        self._fails = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return time.monotonic() >= self._open_until

    def on_success(self) -> None:
        with self._lock:
            self._fails = 0
            self._open_until = 0.0

    def on_failure(self, *, risk: bool) -> None:
        with self._lock:
            if not risk:
                self._fails = min(self._fails + 1, self.fail_threshold)
            else:
                self._fails += 1
            if self._fails >= self.fail_threshold or risk:
                self._open_until = time.monotonic() + self.cool_seconds
                print(
                    f"[rate] 发送熔断 {self.cool_seconds:.0f}s "
                    f"(fails={self._fails}, risk={risk})"
                )

    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self._open_until - time.monotonic())


_RISK_MARKERS = (
    "风控",
    "频繁",
    "禁言",
    "限流",
    "too many",
    "rate limit",
    "1200",
    "1203",
    "1210",
    "blocked",
    "risk",
    "spam",
    "敏感",
)


def is_risk_error(err: Any) -> bool:
    text = str(err or "").lower()
    return any(m.lower() in text for m in _RISK_MARKERS)


_BUCKET: TokenBucket | None = None
_BREAKER: SendCircuitBreaker | None = None
_INIT_LOCK = threading.Lock()


def get_send_bucket() -> TokenBucket:
    global _BUCKET
    if _BUCKET is None:
        with _INIT_LOCK:
            if _BUCKET is None:
                from agent.config import SEND_BUCKET_CAPACITY, SEND_BUCKET_REFILL

                _BUCKET = TokenBucket(
                    capacity=SEND_BUCKET_CAPACITY,
                    refill_rate=SEND_BUCKET_REFILL,
                )
    return _BUCKET


def get_send_breaker() -> SendCircuitBreaker:
    global _BREAKER
    if _BREAKER is None:
        with _INIT_LOCK:
            if _BREAKER is None:
                from agent.config import SEND_BREAKER_COOL, SEND_BREAKER_FAILS

                _BREAKER = SendCircuitBreaker(
                    fail_threshold=SEND_BREAKER_FAILS,
                    cool_seconds=SEND_BREAKER_COOL,
                )
    return _BREAKER


def jitter_sleep(base: float, *, low: float | None = None, high: float | None = None) -> None:
    """在 [low, high] 或 base±40% 内随机休眠。"""
    from agent.config import SEND_JITTER_MAX, SEND_JITTER_MIN

    lo = SEND_JITTER_MIN if low is None else low
    hi = SEND_JITTER_MAX if high is None else high
    if hi < lo:
        lo, hi = hi, lo
    # 若调用方给了 base，夹到抖动区间附近
    center = max(lo, min(hi, base if base > 0 else (lo + hi) / 2))
    span = max(0.05, (hi - lo) / 2)
    delay = random.uniform(max(lo, center - span), min(hi, center + span))
    time.sleep(delay)
