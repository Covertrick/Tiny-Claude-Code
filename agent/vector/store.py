"""sqlite-vec 向量索引；扩展不可用时回退为 BLOB + 暴力余弦。"""

from __future__ import annotations

import json
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Iterable

_INDEXES: dict[str, "VectorIndex"] = {}
_LOCK = threading.Lock()


def _vector_dir() -> Path:
    from agent import config as cfg

    return Path(cfg.VECTOR_DIR)


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(dot / (na * nb))


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass
        return False


class VectorIndex:
    """按 namespace 隔离的向量库（knowledge / vault / …）。"""

    def __init__(self, namespace: str, *, dim: int | None = None) -> None:
        vdir = _vector_dir()
        vdir.mkdir(parents=True, exist_ok=True)
        self.namespace = namespace
        self.path = vdir / f"{namespace}.vec.db"
        self._lock = threading.RLock()
        self._dim = dim
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._vec = _try_load_sqlite_vec(self._conn)
        self._ensure_schema()

    @property
    def backend(self) -> str:
        return "sqlite-vec" if self._vec else "sqlite-blob"

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                meta_json TEXT NOT NULL DEFAULT '{}',
                dim INTEGER NOT NULL,
                embedding BLOB NOT NULL
            )
            """
        )
        if self._vec:
            # dim 未知时先不建 vec0；首次 upsert 再建
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key='dim'"
            ).fetchone()
            if row:
                self._dim = int(row[0])
                self._ensure_vec_table(self._dim)
        self._conn.commit()

    def _ensure_vec_table(self, dim: int) -> None:
        if not self._vec:
            return
        exists = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_items'"
        ).fetchone()
        if exists:
            return
        self._conn.execute(
            f"CREATE VIRTUAL TABLE vec_items USING vec0(embedding float[{int(dim)}])"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vec_map (id TEXT PRIMARY KEY, rowid INTEGER UNIQUE)"
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('dim', ?)",
            (str(dim),),
        )
        self._dim = dim

    def upsert(
        self,
        item_id: str,
        embedding: list[float],
        *,
        meta: dict | None = None,
    ) -> None:
        if not embedding:
            return
        dim = len(embedding)
        blob = _pack(embedding)
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        with self._lock:
            if self._dim is None:
                self._dim = dim
            if self._dim != dim:
                # 维度变更：重建（罕见，换 embedding 模型时）
                self._rebuild_dim(dim)
            if self._vec:
                self._ensure_vec_table(dim)
            self._conn.execute(
                """
                INSERT INTO items(id, meta_json, dim, embedding)
                VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    meta_json=excluded.meta_json,
                    dim=excluded.dim,
                    embedding=excluded.embedding
                """,
                (item_id, meta_json, dim, blob),
            )
            if self._vec:
                self._upsert_vec(item_id, embedding)
            self._conn.commit()

    def _upsert_vec(self, item_id: str, embedding: list[float]) -> None:
        from sqlite_vec import serialize_float32

        packed = serialize_float32(embedding)
        row = self._conn.execute(
            "SELECT rowid FROM vec_map WHERE id=?", (item_id,)
        ).fetchone()
        if row:
            rid = int(row[0])
            self._conn.execute("DELETE FROM vec_items WHERE rowid=?", (rid,))
            self._conn.execute(
                "INSERT INTO vec_items(rowid, embedding) VALUES(?, ?)",
                (rid, packed),
            )
        else:
            cur = self._conn.execute(
                "INSERT INTO vec_items(embedding) VALUES(?)", (packed,)
            )
            rid = int(cur.lastrowid)
            self._conn.execute(
                "INSERT OR REPLACE INTO vec_map(id, rowid) VALUES(?, ?)",
                (item_id, rid),
            )

    def delete(self, item_id: str) -> None:
        with self._lock:
            if self._vec:
                row = self._conn.execute(
                    "SELECT rowid FROM vec_map WHERE id=?", (item_id,)
                ).fetchone()
                if row:
                    self._conn.execute(
                        "DELETE FROM vec_items WHERE rowid=?", (int(row[0]),)
                    )
                    self._conn.execute("DELETE FROM vec_map WHERE id=?", (item_id,))
            self._conn.execute("DELETE FROM items WHERE id=?", (item_id,))
            self._conn.commit()

    def search(
        self,
        query: list[float],
        *,
        top_k: int = 5,
        min_score: float = 0.0,
        filter_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float, dict]]:
        """返回 (id, score, meta)；score 为余弦相似度（越高越好）。"""
        if not query:
            return []
        allow = set(filter_ids) if filter_ids is not None else None
        with self._lock:
            if self._vec and self._dim and len(query) == self._dim:
                hits = self._search_vec(query, top_k=max(top_k * 4, top_k), allow=allow)
            else:
                hits = self._search_blob(query, top_k=top_k * 4 if allow else top_k)
            out: list[tuple[str, float, dict]] = []
            for iid, score, meta in hits:
                if allow is not None and iid not in allow:
                    continue
                if score < min_score:
                    continue
                out.append((iid, score, meta))
                if len(out) >= top_k:
                    break
            return out

    def _search_vec(
        self,
        query: list[float],
        *,
        top_k: int,
        allow: set[str] | None,
    ) -> list[tuple[str, float, dict]]:
        from sqlite_vec import serialize_float32

        packed = serialize_float32(query)
        # sqlite-vec distance：越小越近；转成近似余弦分
        rows = self._conn.execute(
            """
            SELECT m.id, v.distance, i.meta_json
            FROM vec_items v
            JOIN vec_map m ON m.rowid = v.rowid
            JOIN items i ON i.id = m.id
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (packed, int(top_k)),
        ).fetchall()
        out: list[tuple[str, float, dict]] = []
        for iid, dist, meta_json in rows:
            if allow is not None and iid not in allow:
                continue
            # L2 → 粗略相似度；同时用 BLOB 精算余弦更稳
            blob = self._conn.execute(
                "SELECT embedding FROM items WHERE id=?", (iid,)
            ).fetchone()
            if blob:
                score = _cosine(query, _unpack(blob[0]))
            else:
                score = 1.0 / (1.0 + float(dist or 0.0))
            try:
                meta = json.loads(meta_json or "{}")
            except Exception:
                meta = {}
            out.append((str(iid), float(score), meta))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    def _search_blob(
        self, query: list[float], *, top_k: int
    ) -> list[tuple[str, float, dict]]:
        rows = self._conn.execute(
            "SELECT id, meta_json, embedding FROM items"
        ).fetchall()
        scored: list[tuple[str, float, dict]] = []
        for iid, meta_json, blob in rows:
            score = _cosine(query, _unpack(blob))
            try:
                meta = json.loads(meta_json or "{}")
            except Exception:
                meta = {}
            scored.append((str(iid), score, meta))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _rebuild_dim(self, dim: int) -> None:
        """换维度时清空向量表并按 items 重建。"""
        if self._vec:
            self._conn.execute("DROP TABLE IF EXISTS vec_items")
            self._conn.execute("DROP TABLE IF EXISTS vec_map")
        self._dim = dim
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('dim', ?)", (str(dim),)
        )
        if self._vec:
            self._ensure_vec_table(dim)
            rows = self._conn.execute(
                "SELECT id, embedding FROM items WHERE dim=?", (dim,)
            ).fetchall()
            for iid, blob in rows:
                self._upsert_vec(str(iid), _unpack(blob))
        self._conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()
            return int(row[0] if row else 0)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


def get_vector_index(namespace: str = "knowledge") -> VectorIndex:
    with _LOCK:
        if namespace not in _INDEXES:
            _INDEXES[namespace] = VectorIndex(namespace)
        return _INDEXES[namespace]
