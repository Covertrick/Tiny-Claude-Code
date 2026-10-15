"""Vault 向量索引：SQLite 存块 + 嵌入；可选同步到 sqlite-vec 持久索引。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from agent.config import VAULT_DB, VECTOR_BACKEND, ensure_runtime_dirs
from agent.embedding import cosine, get_embedder

_LOCK = threading.Lock()
_INDEX: "VaultIndex | None" = None


@dataclass
class VaultHit:
    path: str
    title: str
    chunk: str
    score: float
    tags: list[str]


def _chunk_vid(path: str, chunk_ix: int) -> str:
    return f"{path}#{int(chunk_ix)}"


class VaultIndex:
    def __init__(self, db_path: Path | None = None):
        ensure_runtime_dirs()
        self.db_path = Path(db_path or VAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = get_embedder()
        self._lock = threading.Lock()
        self._vindex = None
        if VECTOR_BACKEND not in ("memory", "off", "none", "0"):
            try:
                from agent.vector import get_vector_index

                self._vindex = get_vector_index("vault")
                print(f"[vault] 向量索引 backend={self._vindex.backend}")
            except Exception as e:
                print(f"[vault] 向量索引不可用: {e}")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vault_files (
                    path TEXT PRIMARY KEY,
                    title TEXT,
                    tags TEXT,
                    mtime REAL,
                    updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS vault_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    chunk_ix INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    UNIQUE(path, chunk_ix)
                );
                CREATE INDEX IF NOT EXISTS idx_vault_chunks_path ON vault_chunks(path);
                """
            )

    def upsert_file(
        self,
        *,
        rel_path: str,
        title: str,
        tags: list[str],
        chunks: list[str],
        mtime: float,
    ) -> int:
        rel_path = rel_path.replace("\\", "/")
        now = time.time()
        with self._lock, self._conn() as conn:
            old = conn.execute(
                "SELECT chunk_ix FROM vault_chunks WHERE path=?", (rel_path,)
            ).fetchall()
            if self._vindex is not None:
                for row in old:
                    try:
                        self._vindex.delete(_chunk_vid(rel_path, int(row[0])))
                    except Exception:
                        pass
            conn.execute("DELETE FROM vault_chunks WHERE path=?", (rel_path,))
            for i, ch in enumerate(chunks):
                vec = self._embedder.embed(f"{title}\n{ch}")
                conn.execute(
                    "INSERT INTO vault_chunks(path, chunk_ix, text, embedding) "
                    "VALUES (?,?,?,?)",
                    (rel_path, i, ch, json.dumps(vec)),
                )
                if self._vindex is not None:
                    try:
                        self._vindex.upsert(
                            _chunk_vid(rel_path, i),
                            vec,
                            meta={"path": rel_path, "chunk_ix": i, "title": title},
                        )
                    except Exception as e:
                        print(f"[vault] vector upsert skip: {e}")
            conn.execute(
                """
                INSERT INTO vault_files(path, title, tags, mtime, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    title=excluded.title,
                    tags=excluded.tags,
                    mtime=excluded.mtime,
                    updated_at=excluded.updated_at
                """,
                (rel_path, title, json.dumps(tags, ensure_ascii=False), mtime, now),
            )
            return len(chunks)

    def remove_file(self, rel_path: str) -> None:
        rel_path = rel_path.replace("\\", "/")
        with self._lock, self._conn() as conn:
            if self._vindex is not None:
                rows = conn.execute(
                    "SELECT chunk_ix FROM vault_chunks WHERE path=?", (rel_path,)
                ).fetchall()
                for row in rows:
                    try:
                        self._vindex.delete(_chunk_vid(rel_path, int(row[0])))
                    except Exception:
                        pass
            conn.execute("DELETE FROM vault_chunks WHERE path=?", (rel_path,))
            conn.execute("DELETE FROM vault_files WHERE path=?", (rel_path,))

    def search(self, query: str, *, top_k: int = 5, min_score: float = 0.15) -> list[VaultHit]:
        q = (query or "").strip()
        if not q:
            return []
        qvec = self._embedder.embed(q)
        hits: list[VaultHit] = []

        if self._vindex is not None:
            try:
                raw = self._vindex.search(qvec, top_k=max(top_k * 8, top_k), min_score=min_score)
                with self._lock, self._conn() as conn:
                    for vid, score, meta in raw:
                        path = str(meta.get("path") or "")
                        chunk_ix = meta.get("chunk_ix")
                        if not path and "#" in vid:
                            path, _, ix = vid.rpartition("#")
                            chunk_ix = int(ix) if ix.isdigit() else 0
                        row = conn.execute(
                            """
                            SELECT c.path, c.text, f.title, f.tags
                            FROM vault_chunks c
                            LEFT JOIN vault_files f ON f.path = c.path
                            WHERE c.path=? AND c.chunk_ix=?
                            """,
                            (path, int(chunk_ix or 0)),
                        ).fetchone()
                        if not row:
                            continue
                        tags = []
                        try:
                            tags = json.loads(row["tags"] or "[]")
                        except Exception:
                            tags = []
                        hits.append(
                            VaultHit(
                                path=row["path"],
                                title=row["title"] or Path(row["path"]).stem,
                                chunk=row["text"],
                                score=float(score),
                                tags=tags if isinstance(tags, list) else [],
                            )
                        )
            except Exception as e:
                print(f"[vault] vector search fallback: {e}")
                hits = []

        if not hits:
            with self._lock, self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT c.path, c.text, c.embedding, f.title, f.tags
                    FROM vault_chunks c
                    LEFT JOIN vault_files f ON f.path = c.path
                    """
                ).fetchall()
            for row in rows:
                try:
                    vec = json.loads(row["embedding"])
                except Exception:
                    continue
                score = cosine(qvec, vec)
                if score < min_score:
                    continue
                tags = []
                try:
                    tags = json.loads(row["tags"] or "[]")
                except Exception:
                    tags = []
                hits.append(
                    VaultHit(
                        path=row["path"],
                        title=row["title"] or Path(row["path"]).stem,
                        chunk=row["text"],
                        score=score,
                        tags=tags if isinstance(tags, list) else [],
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        seen: set[str] = set()
        out: list[VaultHit] = []
        for h in hits:
            if h.path in seen:
                continue
            seen.add(h.path)
            out.append(h)
            if len(out) >= top_k:
                break
        return out

    def list_files(self, *, limit: int = 100) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT path, title, tags, mtime, updated_at "
                "FROM vault_files ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            try:
                tags = json.loads(r["tags"] or "[]")
            except Exception:
                tags = []
            out.append(
                {
                    "path": r["path"],
                    "title": r["title"],
                    "tags": tags,
                    "mtime": r["mtime"],
                    "updated_at": r["updated_at"],
                }
            )
        return out

    def stats(self) -> dict:
        with self._lock, self._conn() as conn:
            files = conn.execute("SELECT COUNT(*) FROM vault_files").fetchone()[0]
            chunks = conn.execute("SELECT COUNT(*) FROM vault_chunks").fetchone()[0]
        out = {"files": int(files), "chunks": int(chunks)}
        if self._vindex is not None:
            try:
                out["vector_backend"] = self._vindex.backend
                out["vector_count"] = self._vindex.count()
            except Exception:
                pass
        return out

    def graph_edges(self, *, limit_nodes: int = 40) -> dict:
        """简易共现图：同 tag 的文件连边；供 Dashboard ECharts。"""
        files = self.list_files(limit=limit_nodes)
        nodes = [
            {"id": f["path"], "name": f["title"] or f["path"], "symbolSize": 28}
            for f in files
        ]
        tag_map: dict[str, list[str]] = {}
        for f in files:
            for t in f.get("tags") or []:
                tag_map.setdefault(str(t), []).append(f["path"])
        edges = []
        seen = set()
        for paths in tag_map.values():
            for i in range(len(paths)):
                for j in range(i + 1, len(paths)):
                    a, b = paths[i], paths[j]
                    key = tuple(sorted((a, b)))
                    if key in seen:
                        continue
                    seen.add(key)
                    edges.append({"source": a, "target": b})
        return {"nodes": nodes, "edges": edges}


def get_vault_index() -> VaultIndex:
    global _INDEX
    with _LOCK:
        if _INDEX is None:
            _INDEX = VaultIndex()
        return _INDEX
