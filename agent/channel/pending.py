"""短时待确认操作（删除文件等），内存态，进程重启即清空。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class PendingDelete:
    user_id: str
    file_id: str
    file_name: str
    summary: str
    local_path: str
    expires_at: float


_LOCK = threading.Lock()
_PENDING: dict[str, PendingDelete] = {}
_TTL = 120.0  # 秒


def set_pending_delete(
    *,
    user_id: str,
    file_id: str,
    file_name: str,
    summary: str = "",
    local_path: str = "",
    ttl: float = _TTL,
) -> PendingDelete:
    item = PendingDelete(
        user_id=str(user_id),
        file_id=str(file_id),
        file_name=file_name,
        summary=summary or "",
        local_path=local_path or "",
        expires_at=time.time() + ttl,
    )
    with _LOCK:
        _PENDING[str(user_id)] = item
    return item


def get_pending_delete(user_id: str) -> PendingDelete | None:
    uid = str(user_id)
    with _LOCK:
        item = _PENDING.get(uid)
        if not item:
            return None
        if time.time() > item.expires_at:
            _PENDING.pop(uid, None)
            return None
        return item


def clear_pending_delete(user_id: str) -> None:
    with _LOCK:
        _PENDING.pop(str(user_id), None)


def pop_pending_delete(user_id: str) -> PendingDelete | None:
    uid = str(user_id)
    with _LOCK:
        item = _PENDING.pop(uid, None)
        if not item:
            return None
        if time.time() > item.expires_at:
            return None
        return item
