"""多租户知识库：情景/语义分层 + 访问衰减 + 可替换嵌入。

落盘：
  memory/private_{user_id}/memories.jsonl
  memory/group_{group_id}/memories.jsonl

layer:
  episodic — 原始情景
  semantic — 归纳后的结构化事实
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.config import (
    MEMORY_DIR,
    RECALL_MIN_SCORE,
    RECALL_TOP_K,
    VECTOR_BACKEND,
    VECTOR_DIR,
    ensure_runtime_dirs,
)
from agent.embedding import cosine, get_embedder


def _use_vector_index() -> bool:
    return VECTOR_BACKEND not in ("memory", "off", "none", "0")

KB_KINDS = ("note", "doc", "preference", "fact")
LAYERS = ("episodic", "semantic")


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
    scope: str = ""
    layer: str = "episodic"
    access_count: int = 0
    last_accessed: str = ""
    archived: bool = False


def scope_for(user_id: str, group_id: str) -> str:
    gid = str(group_id or "private")
    if gid == "private":
        return f"private:{user_id}"
    return f"group:{gid}"


def scope_subdir(scope: str) -> str:
    if scope.startswith("private:"):
        return f"private_{scope.split(':', 1)[1]}"
    if scope.startswith("group:"):
        return f"group_{scope.split(':', 1)[1]}"
    raise ValueError(f"非法 scope: {scope}")


def scope_dir(scope: str, root: Path | None = None) -> Path:
    return (root or MEMORY_DIR) / scope_subdir(scope)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeStore:
    def __init__(self, root: Path | None = None):
        ensure_runtime_dirs()
        self.root = root or MEMORY_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._embedder = get_embedder()
        self._lock = threading.RLock()
        self._records: list[MemoryRecord] = []
        self._vectors: list[list[float]] = []
        self._vindex = None
        if _use_vector_index():
            try:
                from agent.vector import get_vector_index

                self._vindex = get_vector_index("knowledge")
                print(f"[knowledge] 向量索引 backend={self._vindex.backend}")
            except Exception as e:
                print(f"[knowledge] 向量索引不可用，内存召回: {e}")
        self._migrate_legacy()
        self._load_all()

    def _index_upsert(self, record: MemoryRecord, vec: list[float]) -> None:
        if self._vindex is None:
            return
        try:
            self._vindex.upsert(
                record.id,
                vec,
                meta={
                    "user_id": record.user_id,
                    "group_id": record.group_id,
                    "kind": record.kind,
                    "scope": record.scope,
                    "layer": record.layer,
                    "archived": bool(record.archived),
                },
            )
        except Exception as e:
            print(f"[knowledge] vector upsert skip: {e}")

    def _index_delete(self, memory_id: str) -> None:
        if self._vindex is None:
            return
        try:
            self._vindex.delete(memory_id)
        except Exception as e:
            print(f"[knowledge] vector delete skip: {e}")

    def _embed_text(self, record: MemoryRecord) -> str:
        return " ".join(
            p
            for p in (record.layer, record.title, record.kind, record.text)
            if p
        )

    def _parse_record(self, raw: dict) -> MemoryRecord:
        user_id = str(raw["user_id"])
        group_id = str(raw.get("group_id") or "private")
        scope = raw.get("scope") or scope_for(user_id, group_id)
        kind = raw.get("kind") or "note"
        if kind not in KB_KINDS:
            kind = "note"
        layer = raw.get("layer") or "episodic"
        if layer not in LAYERS:
            layer = "episodic"
        return MemoryRecord(
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
            layer=layer,
            access_count=int(raw.get("access_count") or 0),
            last_accessed=str(raw.get("last_accessed") or ""),
            archived=bool(raw.get("archived") or False),
        )

    def _migrate_legacy(self) -> None:
        legacy = VECTOR_DIR / "memories.jsonl"
        if not legacy.exists():
            return
        marker = self.root / ".migrated_from_vector"
        if marker.exists():
            return
        try:
            for line in legacy.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                record = self._parse_record(json.loads(line))
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
                    record = self._parse_record(json.loads(line))
                    vec = self._embedder.embed(self._embed_text(record))
                    self._records.append(record)
                    self._vectors.append(vec)
                    self._index_upsert(record, vec)

    def _append_disk(self, record: MemoryRecord) -> None:
        d = scope_dir(record.scope, self.root)
        d.mkdir(parents=True, exist_ok=True)
        with (d / "memories.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

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
        layer: str = "episodic",
    ) -> MemoryRecord:
        text = (text or "").strip()
        if not text:
            raise ValueError("知识内容不能为空")
        kind = kind if kind in KB_KINDS else "note"
        layer = layer if layer in LAYERS else "episodic"
        title = (title or "").strip()
        scope = scope_for(user_id, group_id)
        meta = dict(metadata or {})
        meta["scope"] = scope
        meta["kind"] = kind
        meta["layer"] = layer
        if title:
            meta["title"] = title
        now = _now_iso()
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            user_id=str(user_id),
            group_id=str(group_id or "private"),
            text=text,
            source=source,
            created_at=now,
            metadata=meta,
            kind=kind,
            title=title,
            scope=scope,
            layer=layer,
            access_count=0,
            last_accessed=now,
            archived=False,
        )
        with self._lock:
            vec = self._embedder.embed(self._embed_text(record))
            self._records.append(record)
            self._vectors.append(vec)
            self._index_upsert(record, vec)
            self._append_disk(record)
        return record

    def kb_add(self, **kwargs: Any) -> MemoryRecord:
        return self.remember(**kwargs)

    def _touch(self, record: MemoryRecord) -> None:
        record.access_count = int(record.access_count or 0) + 1
        record.last_accessed = _now_iso()

    def recall(
        self,
        *,
        user_id: str,
        query: str,
        group_id: str | None = None,
        top_k: int | None = None,
        kind: str | None = None,
        include_archived: bool = False,
        prefer_semantic: bool = True,
        min_score: float | None = None,
        touch: bool = True,
    ) -> list[tuple[MemoryRecord, float]]:
        top_k = top_k or RECALL_TOP_K
        floor = RECALL_MIN_SCORE if min_score is None else float(min_score)
        qvec = self._embedder.embed(query or "")
        hits: list[tuple[MemoryRecord, float]] = []
        with self._lock:
            eligible: list[tuple[MemoryRecord, list[float]]] = []
            for record, vec in zip(self._records, self._vectors):
                if not self._visible(record, user_id=user_id, group_id=group_id):
                    continue
                if kind and record.kind != kind:
                    continue
                if record.archived and not include_archived:
                    continue
                eligible.append((record, vec))

            by_id = {r.id: (r, v) for r, v in eligible}
            used_index = False
            if self._vindex is not None and by_id:
                try:
                    raw = self._vindex.search(
                        qvec,
                        top_k=min(max(top_k * 5, top_k), len(by_id)),
                        min_score=0.0,
                        filter_ids=by_id.keys(),
                    )
                    for mid, score, _meta in raw:
                        pair = by_id.get(mid)
                        if not pair:
                            continue
                        record, _vec = pair
                        if prefer_semantic and record.layer == "semantic":
                            score += 0.05
                        score *= self._decay_weight(record)
                        if score < floor:
                            continue
                        hits.append((record, score))
                    used_index = bool(hits)
                except Exception as e:
                    print(f"[knowledge] vector search fallback: {e}")

            # 索引为空或与 JSONL 不同步时，回退内存余弦，避免召回被吃掉
            if not used_index:
                for record, vec in eligible:
                    score = cosine(qvec, vec)
                    if prefer_semantic and record.layer == "semantic":
                        score += 0.05
                    score *= self._decay_weight(record)
                    if score < floor:
                        continue
                    hits.append((record, score))

            if not hits and floor > 0.18:
                # 哈希向量分偏低时再放宽一次，避免「明明记过却说没有」
                for record, vec in eligible:
                    score = cosine(qvec, vec)
                    if prefer_semantic and record.layer == "semantic":
                        score += 0.05
                    score *= self._decay_weight(record)
                    if score < 0.18:
                        continue
                    hits.append((record, score))
            hits.sort(key=lambda x: x[1], reverse=True)
            out = hits[:top_k]
            if touch:
                touched_scopes: set[str] = set()
                for rec, _ in out:
                    self._touch(rec)
                    if rec.scope:
                        touched_scopes.add(rec.scope)
                for sc in touched_scopes:
                    self._rewrite_scope(sc)
        return out

    @staticmethod
    def _visible(record: MemoryRecord, *, user_id: str, group_id: str | None) -> bool:
        """私聊看本人全部；群聊看本群 + 本人私聊，不看别的群。"""
        if str(record.user_id) != str(user_id):
            return False
        if group_id is None:
            return True
        gid = str(record.group_id or "private")
        return gid in (str(group_id), "private")

    @staticmethod
    def _decay_weight(record: MemoryRecord) -> float:
        """访问越多权重越高；越久未访问权重越低。"""
        base = 1.0 + min(0.3, 0.02 * int(record.access_count or 0))
        last = record.last_accessed or record.created_at
        if not last:
            return base * (0.5 if record.layer == "episodic" else 1.0)
        try:
            dt = datetime.fromisoformat(last)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
        except Exception:
            return base
        # 半衰期约 14 天
        decay = 0.5 ** (days / 14.0)
        floor = 0.35 if record.layer == "semantic" else 0.2
        return base * max(floor, decay)

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
            self._index_delete(deleted.id)
            self._rewrite_scope(deleted.scope)
            return True

    def kb_delete(self, **kwargs: Any) -> bool:
        return self.delete(**kwargs)

    def get(self, *, user_id: str, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            for record in self._records:
                if str(record.user_id) == str(user_id) and record.id == memory_id:
                    return record
        return None

    def list_for_user(
        self, *, user_id: str, limit: int = 100, include_archived: bool = True
    ) -> list[MemoryRecord]:
        with self._lock:
            recs = [
                r
                for r in self._records
                if str(r.user_id) == str(user_id)
                and (include_archived or not r.archived)
            ]
            recs.sort(key=lambda r: r.created_at or "", reverse=True)
            return recs[:limit]

    def update_record(
        self,
        *,
        memory_id: str,
        user_id: str,
        text: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        source: str | None = None,
        layer: str | None = None,
        kind: str | None = None,
    ) -> MemoryRecord | None:
        """原地更新条目并重算嵌入（Upsert 物理刷新）。"""
        with self._lock:
            for i, record in enumerate(self._records):
                if record.id != memory_id or str(record.user_id) != str(user_id):
                    continue
                if text is not None:
                    record.text = text.strip()
                if title is not None:
                    record.title = title.strip()
                if source is not None:
                    record.source = source
                if layer is not None and layer in LAYERS:
                    record.layer = layer
                if kind is not None and kind in KB_KINDS:
                    record.kind = kind
                if metadata is not None:
                    record.metadata = dict(metadata)
                    record.metadata["scope"] = record.scope
                    record.metadata["kind"] = record.kind
                    record.metadata["layer"] = record.layer
                    if record.title:
                        record.metadata["title"] = record.title
                record.last_accessed = _now_iso()
                vec = self._embedder.embed(self._embed_text(record))
                self._vectors[i] = vec
                self._index_upsert(record, vec)
                self._rewrite_scope(record.scope)
                return record
        return None

    def archive_stale(
        self,
        *,
        max_age_days: float = 21,
        min_access: int = 1,
        only_episodic: bool = True,
    ) -> int:
        """遗忘：长期低访问情景记忆归档（不删，检索默认跳过）。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        n = 0
        scopes: set[str] = set()
        with self._lock:
            for rec in self._records:
                if rec.archived:
                    continue
                if only_episodic and rec.layer != "episodic":
                    continue
                if int(rec.access_count or 0) >= min_access and rec.layer == "semantic":
                    continue
                stamp = rec.last_accessed or rec.created_at
                try:
                    dt = datetime.fromisoformat(stamp)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if dt < cutoff and int(rec.access_count or 0) < max(2, min_access + 1):
                    rec.archived = True
                    n += 1
                    if rec.scope:
                        scopes.add(rec.scope)
            for sc in scopes:
                self._rewrite_scope(sc)
        if n:
            print(f"[knowledge] 归档低价值情景记忆 {n} 条")
        return n

    def consolidate_user(
        self, *, user_id: str, group_id: str = "private", limit: int = 12
    ) -> int:
        """增量语义归纳：情景 → 知识卡片 Upsert/Merge。"""
        from agent.knowledge.synthesis import synthesize_user_episodic

        return synthesize_user_episodic(
            user_id=user_id, group_id=group_id, limit=limit
        )

    def consolidate_all(self, *, min_episodic: int = 3) -> int:
        users: dict[str, int] = {}
        with self._lock:
            for r in self._records:
                if r.archived or r.layer != "episodic":
                    continue
                if (r.metadata or {}).get("synthesized"):
                    continue
                users[str(r.user_id)] = users.get(str(r.user_id), 0) + 1
        n = 0
        for uid, cnt in users.items():
            if cnt < min_episodic:
                continue
            done = self.consolidate_user(user_id=uid)
            if done:
                n += 1
        if n:
            print(f"[knowledge] 增量卡片归纳完成 {n} 个用户")
        return n

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
