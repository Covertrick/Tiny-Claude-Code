"""Harness 约束快照。晋升前留下旧文本，回滚按 id 恢复。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.harness.evolve.whitelist import EDITABLE, assert_editable
from agent.harness.store import harness_root


def _dir() -> Path:
    path = harness_root() / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file(name: str) -> Path:
    assert_editable(name, "")
    return harness_root() / name


def read_text(name: str = "guardrails.md") -> str:
    path = _file(name)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(name: str, text: str) -> None:
    assert_editable(name, text)
    path = _file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")


def current_rev() -> str:
    pointer = harness_root() / "active_rev.txt"
    if not pointer.is_file():
        return "base"
    return pointer.read_text(encoding="utf-8").strip() or "base"


def _set_rev(rev: str) -> None:
    pointer = harness_root() / "active_rev.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(rev, encoding="utf-8")


def save_snapshot(*, label: str, files: dict[str, str] | None = None) -> str:
    rev = "snap_" + uuid.uuid4().hex[:10]
    payload = {
        "id": rev,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files
        if files is not None
        else {name: read_text(name) for name in EDITABLE},
    }
    (_dir() / f"{rev}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return rev


def load_snapshot(rev: str) -> dict:
    path = _dir() / f"{rev}.json"
    if not path.is_file():
        raise FileNotFoundError(rev)
    return json.loads(path.read_text(encoding="utf-8"))


def restore_snapshot(rev: str) -> str:
    data = load_snapshot(rev)
    for name, text in (data.get("files") or {}).items():
        if name not in EDITABLE:
            continue
        write_text(name, text or "")
    _set_rev(rev)
    return rev


def activate(rev: str) -> None:
    _set_rev(rev)
