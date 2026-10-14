"""多租户知识库：目录隔离 + scope 元数据过滤。

落盘：
  memory/private_{user_id}/memories.jsonl
  memory/group_{group_id}/memories.jsonl   # 记录内带 user_id，检索仍按用户过滤

检索：
  群聊 → scope=group:{gid} 且 user_id 匹配
  私聊 → 该 user 的 private + 其所有 group 记录（可选只 private；此处私聊可读全部）
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import MEMORY_DIR, RECALL_TOP_K, VECTOR_DIR, ensure_runtime_dirs

KB_KINDS = ("note", "doc", "preference")


@dataclass
class MemoryRecord:
    id: str
    user_id: str
    group_id: str
    text: str
    source: str
    created_at: str
    metadata: dict[str, Any]
    kind: str = "note"
    title: str = ""
    scope: str = ""  # private:{uid} | group:{gid}


def scope_for(user_id: str, group_id: str) -> str:
    gid = str(group_id or "private")
    if gid == "private":
        return f"private:{user_id}"
    return f"group:{gid}"


def scope_subdir(scope: str) -> str:
    """scope → 相对目录名 private_{uid} / group_{gid}。"""
    if scope.startswith("private:"):
        return f"private_{scope.split(':', 1)[1]}"
    if scope.startswith("group:"):
        return f"group_{scope.split(':', 1)[1]}"
    raise ValueError(f"非法 scope: {scope}")


def scope_dir(scope: str, root: Path | None = None) -> Path:
    return (root or MEMORY_DIR) / scope_subdir(scope)


class _HashEmbedding:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        import hashlib
        import math
        import re

        vec = [0.0] * self.dim
        tokens = re.findall(r"[\u4e00-\u9fff]{1,2}|[a-zA-Z0-9_]+", text.lower())
        if not tokens:
            tokens = [text.lower()[:32] or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for i in range(0, min(len(digest), 32), 2):
                idx = int.from_bytes(digest[i : i + 2], "big") % self.dim
                sign = 1.0 if digest[i] % 2 == 0 else -1.0
                vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class KnowledgeStore:
    def __init__(self, root: Path | None = None):
        ensure_runtime_dirs()
        self.root = root or MEMORY_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._embedder = _HashEmbedding()
        self._lock = threading.RLock()
        self._records: list[MemoryRecord] = []
        self._vectors: list[list[float]] = []
        self._migrate_legacy()
        self._load_all()

    def _embed_text(self, record: MemoryRecord) -> str:
        return " ".join(p for p in (record.title, record.kind, record.text) if p)

    def _migrate_legacy(self) -> None:
        legacy = VECTOR_DIR / "memories.jsonl"
        if not legacy.exists():
            return
        marker = self.root / ".migrated_from_vector"
        if marker.exists():
            return
        try:
            lines = legacy.read_text(encoding="utf-8").splitlines()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                user_id = str(raw["user_id"])
                group_id = str(raw.get("group_id") or "private")
                scope = scope_for(user_id, group_id)
                record = MemoryRecord(
                    id=raw["id"],
                    user_id=user_id,
                    group_id=group_id,
                    text=raw["text"],
                    source=raw.get("source") or ("private" if group_id == "private" else "group"),
                    created_at=raw.get("created_at") or "",
                    metadata=raw.get("metadata") or {},
                    kind=raw.get("kind") or "note",
                    title=str(raw.get("title") or ""),
                    scope=scope,
                )
                self._append_disk(record)
            marker.write_text("ok", encoding="utf-8")
        except Exception as e:
            print(f"[knowledge] legacy migrate skip: {e}")

    def _load_all(self) -> None:
        if not self.root.exists():
            return
        for path in self.root.rglob("memories.jsonl"):
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    raw = json.loads(line)
                    user_id = str(raw["user_id"])
                    group_id = str(raw.get("group_id") or "private")
                    scope = raw.get("scope") or scope_for(user_id, group_id)
                    kind = raw.get("kind") or "note"
                    if kind not in KB_KINDS:
                        kind = "note"
                    record = MemoryRecord(
                        id=raw["id"],
                        user_id=user_id,
                        group_id=group_id,
                        text=raw["text"],
                        source=raw.get("source") or "group",
                        created_at=raw.get("created_at") or "",
                        metadata=raw.get("metadata") or {},
                        kind=kind,
                        title=str(raw.get("title") or ""),
                        scope=scope,
                    )
                    self._records.append(record)
                    self._vectors.append(self._embedder.embed(self._embed_text(record)))

    def _append_disk(self, record: MemoryRecord) -> None:
        d = scope_dir(record.scope, self.root)
        d.mkdir(parents=True, exist_ok=True)
        with (d / "memories.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    def remember(
        self,
        *,
        user_id: str,
        group_id: str,
        text: str,
        source: str,
        metadata: dict[str, Any] | None = None,
        kind: str = "note",
        title: str = "",
    ) -> MemoryRecord:
        text = (text or "").strip()
        if not text:
            raise ValueError("知识内容不能为空")
        kind = kind if kind in KB_KINDS else "note"
        title = (title or "").strip()
        scope = scope_for(user_id, group_id)
        meta = dict(metadata or {})
        meta["scope"] = scope
        meta["kind"] = kind
        if title:
            meta["title"] = title
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            user_id=str(user_id),
            group_id=str(group_id or "private"),
            text=text,
            source=source,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=meta,
            kind=kind,
            title=title,
            scope=scope,
        )
        with self._lock:
            self._records.append(record)
            self._vectors.append(self._embedder.embed(self._embed_text(record)))
            self._append_disk(record)
        return record

    def kb_add(self, **kwargs: Any) -> MemoryRecord:
        return self.remember(**kwargs)

    def recall(
        self,
        *,
        user_id: str,
        query: str,
        group_id: str | None = None,
        top_k: int | None = None,
        kind: str | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        top_k = top_k or RECALL_TOP_K
        qvec = self._embedder.embed(query or "")
        hits: list[tuple[MemoryRecord, float]] = []
        with self._lock:
            for record, vec in zip(self._records, self._vectors):
                if str(record.user_id) != str(user_id):
                    continue
                if group_id is not None and str(record.group_id) != str(group_id):
                    continue
                if kind and record.kind != kind:
                    continue
                # scope 双重校验
                if group_id is not None:
                    expect = scope_for(user_id, group_id)
                    if record.scope and record.scope != expect:
                        # 允许旧数据缺 scope
                        if record.scope.startswith("group:") or record.scope.startswith(
                            "private:"
                        ):
                            continue
                hits.append((record, self._cosine(qvec, vec)))
        hits.sort(key=lambda x: x[1], reverse=True)
        return hits[:top_k]

    def kb_search(self, **kwargs: Any) -> list[tuple[MemoryRecord, float]]:
        return self.recall(**kwargs)

    def delete(self, *, user_id: str, memory_id: str) -> bool:
        with self._lock:
            kept_r: list[MemoryRecord] = []
            kept_v: list[list[float]] = []
            deleted: MemoryRecord | None = None
            for record, vec in zip(self._records, self._vectors):
                if str(record.user_id) == str(user_id) and record.id == memory_id:
                    deleted = record
                    continue
                kept_r.append(record)
                kept_v.append(vec)
            if deleted is None:
                return False
            self._records = kept_r
            self._vectors = kept_v
            self._rewrite_scope(deleted.scope)
            return True

    def kb_delete(self, **kwargs: Any) -> bool:
        return self.delete(**kwargs)

    def _rewrite_scope(self, scope: str) -> None:
        if not scope:
            return
        path = scope_dir(scope, self.root) / "memories.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for record in self._records:
                if record.scope == scope:
                    f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


_STORE: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _STORE
    if _STORE is None:
        _STORE = KnowledgeStore()
    return _STORE
