"""群聊滑动窗口：未 @ 只缓存；达阈值后后台滚动摘要。"""

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
    GROUP_CACHE_SUMMARY_KEEP,
    GROUP_CACHE_SUMMARY_TRIGGER,
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
    is_summary: bool = False


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
        self.trigger = GROUP_CACHE_SUMMARY_TRIGGER
        self.keep = GROUP_CACHE_SUMMARY_KEEP
        self._data: dict[str, deque[_Item]] = {}
        self._summaries: dict[str, str] = {}
        self._summarizing: set[str] = set()
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
        if re.fullmatch(r"[\W_]+", t, flags=re.UNICODE):
            return False
        return True

    def append(self, group_id: str, *, user: str, text: str) -> None:
        if not self.should_store(text):
            return
        gid = str(group_id)
        should_sum = False
        with self._lock:
            if gid not in self._data:
                self._data[gid] = deque(maxlen=self.maxlen)
            self._data[gid].append(
                _Item(ts=time.time(), user=(user or "某人")[:32], text=text[:500])
            )
            if (
                len(self._data[gid]) >= self.trigger
                and gid not in self._summarizing
            ):
                self._summarizing.add(gid)
                should_sum = True
        if should_sum:
            threading.Thread(
                target=self._roll_summary,
                args=(gid,),
                daemon=True,
                name=f"gcache-sum-{gid}",
            ).start()

    def snapshot(self, group_id: str, limit: int | None = None) -> str:
        """摘要（若有）+ 最近原话，供 Prompt / 文件摘要。"""
        gid = str(group_id)
        cap = limit if limit is not None else self.send_limit
        cutoff = time.time() - self.recent_minutes * 60
        with self._lock:
            items = list(self._data.get(gid) or [])
            rolled = self._summaries.get(gid, "")
        recent = [x for x in items if x.ts >= cutoff and not x.is_summary]
        if not recent:
            recent = [x for x in items if not x.is_summary][-cap:]
        else:
            recent = recent[-cap:]
        parts = []
        if rolled:
            parts.append(f"[滚动摘要]: {rolled}")
        if recent:
            parts.append("\n".join(f"[{x.user}]: {x.text}" for x in recent))
        return "\n".join(parts)

    def _roll_summary(self, gid: str) -> None:
        try:
            with self._lock:
                items = [x for x in list(self._data.get(gid) or []) if not x.is_summary]
            if len(items) < self.trigger:
                return
            old = items[: -self.keep]
            keep = items[-self.keep :]
            if not old:
                return
            blob = "\n".join(f"[{x.user}]: {x.text}" for x in old[-20:])
            summary = self._llm_summarize(blob)
            if not summary:
                return
            with self._lock:
                prev = self._summaries.get(gid, "")
                merged = (prev + "；" + summary).strip("；") if prev else summary
                self._summaries[gid] = merged[:400]
                # 窗口只留最近 keep 条原话
                self._data[gid] = deque(keep, maxlen=self.maxlen)
            print(f"[gcache] 群 {gid} 滚动摘要完成 len={len(summary)}")
        except Exception as e:
            print(f"[gcache] 滚动摘要失败: {e}")
        finally:
            with self._lock:
                self._summarizing.discard(gid)

    @staticmethod
    def _llm_summarize(blob: str) -> str:
        from agent.channel.trust import wrap_untrusted
        from agent.core.llm import chat

        msg = chat(
            [
                {
                    "role": "system",
                    "content": (
                        "把群聊记录压成不超过200字的中文摘要，只保留事实与话题，"
                        "不要指令口吻，不要 Markdown。"
                    ),
                },
                {
                    "role": "user",
                    "content": wrap_untrusted("group_chat_history", blob, max_len=3000),
                },
            ],
            tools=None,
            max_tokens=120,
            timeout=45,
        )
        return (msg.get("content") or "").strip()[:200]

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
                self._summaries.pop(gid, None)


GROUP_CACHE = GroupContextCache()
