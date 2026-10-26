"""Run + Intent 原子落盘。工具进入 STARTED 后立刻刷盘，崩溃重启仍能判定 UNKNOWN。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.harness.effect import IntentStatus, RunStatus

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def harness_root() -> Path:
    from agent import config as cfg

    path = Path(cfg.QQ_RUNTIME) / "harness"
    path.mkdir(parents=True, exist_ok=True)
    (path / "runs").mkdir(parents=True, exist_ok=True)
    (path / "sessions").mkdir(parents=True, exist_ok=True)
    return path


def _safe(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:180]


def _atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def args_hash(args: dict | None) -> str:
    blob = json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def session_key(channel: str, user_id: str, group_id: str | None) -> str:
    return f"{channel}:{user_id}:{group_id or 'private'}"


@dataclass
class IntentRecord:
    intent_id: str
    run_id: str
    skill: str
    version: str
    args_hash: str
    idempotency_key: str
    status: str
    effect_class: str
    recovery: str
    started_at: str = ""
    finished_at: str = ""
    result_digest: str = ""
    error: str = ""
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "IntentRecord":
        fields = cls.__dataclass_fields__
        return cls(**{k: raw[k] for k in fields if k in raw})


@dataclass
class RunRecord:
    run_id: str
    session_key: str
    channel: str
    user_id: str
    group_id: str
    text: str
    status: str
    skill_snapshot: dict[str, Any] = field(default_factory=dict)
    require_contract: bool = True
    error: str = ""
    reply: str = ""
    harness_rev: str = ""
    guardrail_text: str = ""
    created_at: str = ""
    updated_at: str = ""
    intents: list[IntentRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> "RunRecord":
        intents = [IntentRecord.from_dict(x) for x in raw.get("intents") or []]
        fields = {
            k: raw[k]
            for k in cls.__dataclass_fields__
            if k in raw and k != "intents"
        }
        return cls(intents=intents, **fields)


class HarnessStore:
    def save(self, run: RunRecord) -> None:
        run.updated_at = _now()
        with _LOCK:
            _atomic(harness_root() / "runs" / f"{run.run_id}.json", run.to_dict())
            sess_path = harness_root() / "sessions" / f"{_safe(run.session_key)}.json"
            sess = _read(sess_path) or {
                "session_key": run.session_key,
                "active_run_id": "",
                "notices": [],
            }
            terminal = {
                RunStatus.SUCCEEDED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
                RunStatus.ABORTED.value,
            }
            if run.status not in terminal:
                sess["active_run_id"] = run.run_id
            elif sess.get("active_run_id") == run.run_id:
                sess["active_run_id"] = ""
            _atomic(sess_path, sess)

    def load(self, run_id: str) -> RunRecord | None:
        raw = _read(harness_root() / "runs" / f"{run_id}.json")
        if not raw:
            return None
        return RunRecord.from_dict(raw)

    def list_runs(self) -> list[RunRecord]:
        out: list[RunRecord] = []
        folder = harness_root() / "runs"
        if not folder.is_dir():
            return out
        for path in folder.glob("*.json"):
            raw = _read(path)
            if raw:
                try:
                    out.append(RunRecord.from_dict(raw))
                except Exception:
                    continue
        return out

    def push_notice(self, key: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with _LOCK:
            path = harness_root() / "sessions" / f"{_safe(key)}.json"
            sess = _read(path) or {
                "session_key": key,
                "active_run_id": "",
                "notices": [],
            }
            notes = list(sess.get("notices") or [])
            if text not in notes:
                notes.append(text)
            sess["notices"] = notes[-8:]
            _atomic(path, sess)

    def consume_notices(self, key: str) -> list[str]:
        with _LOCK:
            path = harness_root() / "sessions" / f"{_safe(key)}.json"
            sess = _read(path) or {
                "session_key": key,
                "active_run_id": "",
                "notices": [],
            }
            notes = list(sess.get("notices") or [])
            sess["notices"] = []
            _atomic(path, sess)
            return notes
