"""按用户/群记录 Token 与调用次数（SQLite）。"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import QQ_RUNTIME, ensure_runtime_dirs

_LOCK = threading.Lock()
_STORE: "UsageStore | None" = None


class UsageStore:
    def __init__(self, db_path: Path | None = None):
        ensure_runtime_dirs()
        self.db_path = db_path or (QQ_RUNTIME / "usage.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'llm',
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    meta TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_events(user_id)"
            )

    def add(
        self,
        *,
        user_id: str = "",
        group_id: str = "",
        kind: str = "llm",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        meta: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO usage_events
                (ts, user_id, group_id, kind, prompt_tokens, completion_tokens, total_tokens, meta)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    now,
                    str(user_id or ""),
                    str(group_id or ""),
                    kind,
                    int(prompt_tokens or 0),
                    int(completion_tokens or 0),
                    int(total_tokens or 0),
                    (meta or "")[:500],
                ),
            )

    def summary(self, *, user_id: str = "", limit_days: int = 30) -> dict[str, Any]:
        with self._lock, self._conn() as conn:
            if user_id:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS calls,
                           COALESCE(SUM(prompt_tokens),0) AS prompt,
                           COALESCE(SUM(completion_tokens),0) AS completion,
                           COALESCE(SUM(total_tokens),0) AS total
                    FROM usage_events WHERE user_id=?
                    """,
                    (str(user_id),),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS calls,
                           COALESCE(SUM(prompt_tokens),0) AS prompt,
                           COALESCE(SUM(completion_tokens),0) AS completion,
                           COALESCE(SUM(total_tokens),0) AS total
                    FROM usage_events
                    """
                ).fetchone()
        return {
            "calls": int(row["calls"] or 0),
            "prompt_tokens": int(row["prompt"] or 0),
            "completion_tokens": int(row["completion"] or 0),
            "total_tokens": int(row["total"] or 0),
            "user_id": user_id or "*",
            "window_days": limit_days,
        }


def get_usage_store() -> UsageStore:
    global _STORE
    with _LOCK:
        if _STORE is None:
            _STORE = UsageStore()
        return _STORE


_ctx_user = threading.local()


def set_usage_context(*, user_id: str = "", group_id: str = "") -> None:
    _ctx_user.user_id = user_id
    _ctx_user.group_id = group_id


def record_usage_from_api(usage: dict) -> None:
    if not usage:
        return
    get_usage_store().add(
        user_id=getattr(_ctx_user, "user_id", "") or "",
        group_id=getattr(_ctx_user, "group_id", "") or "",
        kind="llm",
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
    )
