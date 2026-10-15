"""群聊近期附件缓存：供「保存上面的文件」检索，不落 LLM。"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecentFile:
    ts: float
    group_id: str
    uploader_id: str
    user: str
    name: str
    url: str = ""
    path: str = ""
    file_id: str = ""
    kind: str = "file"
    raw: dict[str, str] = field(default_factory=dict)


class RecentFileCache:
    def __init__(self, maxlen: int = 30, ttl_seconds: float = 3600):
        self.maxlen = maxlen
        self.ttl_seconds = ttl_seconds
        self._data: dict[str, deque[RecentFile]] = {}
        self._lock = threading.RLock()

    def append(
        self,
        group_id: str,
        *,
        uploader_id: str,
        user: str,
        segments: list[dict[str, str]],
    ) -> None:
        gid = str(group_id or "")
        if not gid or not segments:
            return
        now = time.time()
        with self._lock:
            if gid not in self._data:
                self._data[gid] = deque(maxlen=self.maxlen)
            dq = self._data[gid]
            for seg in segments:
                name = (seg.get("name") or "").strip() or "file.bin"
                item = RecentFile(
                    ts=now,
                    group_id=gid,
                    uploader_id=str(uploader_id or ""),
                    user=(user or uploader_id or "")[:32],
                    name=name,
                    url=str(seg.get("url") or ""),
                    path=str(seg.get("path") or ""),
                    file_id=str(seg.get("file_id") or ""),
                    kind=str(seg.get("kind") or "file"),
                    raw=dict(seg),
                )
                dq.append(item)

    def recent(
        self,
        group_id: str,
        *,
        limit: int = 5,
        within_seconds: float | None = None,
        uploader_id: str | None = None,
    ) -> list[RecentFile]:
        gid = str(group_id or "")
        cutoff = time.time() - (
            within_seconds if within_seconds is not None else self.ttl_seconds
        )
        with self._lock:
            items = list(self._data.get(gid) or [])
        out = [x for x in items if x.ts >= cutoff]
        if uploader_id:
            mine = [x for x in out if x.uploader_id == str(uploader_id)]
            if mine:
                out = mine
        return list(reversed(out[-limit:]))  # 最新在前

    def latest(self, group_id: str, *, uploader_id: str | None = None) -> RecentFile | None:
        items = self.recent(group_id, limit=1, uploader_id=uploader_id)
        return items[0] if items else None

    def to_segment(self, item: RecentFile) -> dict[str, str]:
        return {
            "kind": item.kind,
            "name": item.name,
            "url": item.url,
            "path": item.path,
            "file_id": item.file_id,
        }


RECENT_FILES = RecentFileCache()
