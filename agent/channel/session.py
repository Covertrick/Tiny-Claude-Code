"""短期记忆：按会话键保存最近若干轮对话。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from agent.config import SESSION_DIR, SHORT_TERM_MAX_TURNS, ensure_runtime_dirs


def session_key(*, user_id: str, group_id: str | None, is_group: bool) -> str:
    if is_group:
        return f"group:{group_id}:user:{user_id}"
    return f"private:user:{user_id}"


class SessionStore:
    def __init__(self) -> None:
        ensure_runtime_dirs()
        self._lock = threading.RLock()
        self._cache: dict[str, list[dict]] = {}

    def _path(self, key: str) -> Path:
        safe = key.replace(":", "_").replace("/", "_")
        return SESSION_DIR / f"{safe}.json"

    def load(self, key: str) -> list[dict]:
        with self._lock:
            if key in self._cache:
                return list(self._cache[key])
            path = self._path(key)
            if not path.exists():
                self._cache[key] = []
                return []
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = data if isinstance(data, list) else []
            self._cache[key] = messages
            return list(messages)

    def append(self, key: str, role: str, content: str) -> list[dict]:
        with self._lock:
            messages = self.load(key)
            messages.append({"role": role, "content": content})
            # 保留最近 N 轮（user+assistant 共 2N）
            max_msgs = SHORT_TERM_MAX_TURNS * 2
            if len(messages) > max_msgs:
                messages = messages[-max_msgs:]
            self._cache[key] = messages
            self._path(key).write_text(
                json.dumps(messages, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return list(messages)

    def clear(self, key: str) -> None:
        with self._lock:
            self._cache[key] = []
            path = self._path(key)
            if path.exists():
                path.unlink()


SESSIONS = SessionStore()
