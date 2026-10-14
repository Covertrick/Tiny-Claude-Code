"""群聊滑动窗口：未 @ 只缓存不调 LLM；@ 时按需取出近期上下文。"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass

from agent.config import (
    GROUP_CACHE_IDLE_SECONDS,
    GROUP_CACHE_MAXLEN,
    GROUP_CACHE_RECENT_MINUTES,
    GROUP_CACHE_SEND_LIMIT,
)

_SPAM = {
    "哈哈哈",
    "哈哈",
    "呵呵",
    "嘿嘿",
    "顶",
    "+1",
    "＋1",
    "1",
    "ok",
    "OK",
    "好的",
    "好",
    "嗯",
    "哦",
    "啊",
    "草",
    "笑死",
    "dd",
    "DD",
}


@dataclass
class _Item:
    ts: float
    user: str
    text: str


class GroupContextCache:
    def __init__(
        self,
        maxlen: int | None = None,
        recent_minutes: int | None = None,
        send_limit: int | None = None,
        idle_seconds: int | None = None,
    ):
        self.maxlen = maxlen or GROUP_CACHE_MAXLEN
        self.recent_minutes = recent_minutes or GROUP_CACHE_RECENT_MINUTES
        self.send_limit = send_limit or GROUP_CACHE_SEND_LIMIT
        self.idle_seconds = idle_seconds or GROUP_CACHE_IDLE_SECONDS
        self._data: dict[str, deque[_Item]] = {}
        self._lock = threading.RLock()
        self._cleaner = threading.Thread(
            target=self._clean_loop, name="group-cache-clean", daemon=True
        )
        self._cleaner.start()

    def should_store(self, text: str) -> bool:
        t = (text or "").strip()
        if len(t) < 2:
            return False
        if t in _SPAM:
            return False
        # 纯表情/符号
        if re.fullmatch(r"[\W_]+", t, flags=re.UNICODE):
            return False
        return True

    def append(self, group_id: str, *, user: str, text: str) -> None:
        if not self.should_store(text):
            return
        gid = str(group_id)
        with self._lock:
            if gid not in self._data:
                self._data[gid] = deque(maxlen=self.maxlen)
            self._data[gid].append(
                _Item(ts=time.time(), user=(user or "某人")[:32], text=text[:500])
            )

    def snapshot(self, group_id: str, limit: int | None = None) -> str:
        """最近 N 分钟内、最多 limit（默认 send_limit）条，供 Prompt / 文件摘要。"""
        gid = str(group_id)
        cap = limit if limit is not None else self.send_limit
        cutoff = time.time() - self.recent_minutes * 60
        with self._lock:
            items = list(self._data.get(gid) or [])
        recent = [x for x in items if x.ts >= cutoff]
        if not recent:
            recent = items[-cap:]
        else:
            recent = recent[-cap:]
        if not recent:
            return ""
        return "\n".join(f"[{x.user}]: {x.text}" for x in recent)

    def _clean_loop(self) -> None:
        while True:
            time.sleep(300)
            try:
                self._purge_idle()
            except Exception:
                pass

    def _purge_idle(self) -> None:
        now = time.time()
        with self._lock:
            dead = []
            for gid, dq in self._data.items():
                if not dq or (now - dq[-1].ts) > self.idle_seconds:
                    dead.append(gid)
            for gid in dead:
                self._data.pop(gid, None)


GROUP_CACHE = GroupContextCache()
