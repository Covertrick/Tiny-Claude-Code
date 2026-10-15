"""结构化用户画像（偏好 / 重要日期 / 备注），与情景记忆分离。"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import MEMORY_DIR, ensure_runtime_dirs

_LOCK = threading.Lock()


@dataclass
class UserProfile:
    user_id: str
    display_name: str = ""
    preferences: list[str] = field(default_factory=list)
    important_dates: dict[str, str] = field(default_factory=dict)  # 标签 -> ISO/描述
    notes: list[str] = field(default_factory=list)
    updated_at: str = ""

    def to_prompt_block(self) -> str:
        lines = []
        if self.display_name:
            lines.append(f"称呼/昵称：{self.display_name}")
        if self.preferences:
            lines.append("偏好：" + "；".join(self.preferences[:12]))
        if self.important_dates:
            dates = "；".join(f"{k}={v}" for k, v in list(self.important_dates.items())[:8])
            lines.append("重要日期：" + dates)
        if self.notes:
            lines.append("备注：" + "；".join(self.notes[:8]))
        return "\n".join(lines) if lines else ""


def _path(user_id: str) -> Path:
    ensure_runtime_dirs()
    d = MEMORY_DIR / f"private_{user_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d / "profile.json"


def load_profile(user_id: str) -> UserProfile:
    p = _path(user_id)
    if not p.is_file():
        return UserProfile(user_id=str(user_id))
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return UserProfile(
            user_id=str(user_id),
            display_name=str(raw.get("display_name") or ""),
            preferences=list(raw.get("preferences") or []),
            important_dates=dict(raw.get("important_dates") or {}),
            notes=list(raw.get("notes") or []),
            updated_at=str(raw.get("updated_at") or ""),
        )
    except Exception:
        return UserProfile(user_id=str(user_id))


def save_profile(profile: UserProfile) -> UserProfile:
    profile.updated_at = datetime.now(timezone.utc).isoformat()
    p = _path(profile.user_id)
    with _LOCK:
        p.write_text(
            json.dumps(asdict(profile), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return profile


def upsert_preference(user_id: str, text: str) -> UserProfile:
    prof = load_profile(user_id)
    t = (text or "").strip()
    if t and t not in prof.preferences:
        prof.preferences = ([t] + prof.preferences)[:30]
        save_profile(prof)
    return prof


def merge_profile_patch(user_id: str, patch: dict[str, Any]) -> UserProfile:
    prof = load_profile(user_id)
    if patch.get("display_name"):
        prof.display_name = str(patch["display_name"])[:64]
    for pref in patch.get("preferences") or []:
        s = str(pref).strip()
        if s and s not in prof.preferences:
            prof.preferences.insert(0, s)
    prof.preferences = prof.preferences[:30]
    for k, v in (patch.get("important_dates") or {}).items():
        if k and v:
            prof.important_dates[str(k)[:32]] = str(v)[:64]
    for n in patch.get("notes") or []:
        s = str(n).strip()
        if s and s not in prof.notes:
            prof.notes.insert(0, s)
    prof.notes = prof.notes[:20]
    return save_profile(prof)
