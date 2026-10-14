"""群文件索引：SQLite File_Index + 本地落盘路径。"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import FILES_DB, GROUP_FILES_DIR, ensure_runtime_dirs


@dataclass
class FileRecord:
    id: str
    group_id: str
    uploader_id: str
    file_name: str
    local_path: str
    summary: str
    tags: str
    create_time: str


def _safe_name(name: str) -> str:
    name = (name or "file.bin").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\u4e00-\u9fff-]+", "_", name)
    return name or "file.bin"


class FileIndexStore:
    def __init__(self, db_path: Path | None = None, files_root: Path | None = None):
        ensure_runtime_dirs()
        self.db_path = db_path or FILES_DB
        self.files_root = files_root or GROUP_FILES_DIR
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_index (
                        id TEXT PRIMARY KEY,
                        group_id TEXT NOT NULL,
                        uploader_id TEXT NOT NULL,
                        file_name TEXT NOT NULL,
                        local_path TEXT NOT NULL DEFAULT '',
                        summary TEXT NOT NULL DEFAULT '',
                        tags TEXT NOT NULL DEFAULT '',
                        create_time TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_file_group ON file_index(group_id)"
                )
                conn.commit()
            finally:
                conn.close()

    def group_dir(self, group_id: str) -> Path:
        gid = str(group_id or "private")
        if "/" in gid or "\\" in gid or ".." in gid:
            raise ValueError("非法 group_id")
        d = (self.files_root / gid).resolve()
        root = self.files_root.resolve()
        if not str(d).startswith(str(root)):
            raise ValueError("路径逃出文件根")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def dest_path(self, group_id: str, file_name: str) -> Path:
        base = _safe_name(file_name)
        dest = self.group_dir(group_id) / base
        if dest.exists():
            stem, suf = dest.stem, dest.suffix
            dest = dest.with_name(f"{stem}_{uuid.uuid4().hex[:6]}{suf}")
        return dest

    def add(
        self,
        *,
        group_id: str,
        uploader_id: str,
        file_name: str,
        local_path: str = "",
        summary: str = "",
        tags: str = "",
    ) -> FileRecord:
        record = FileRecord(
            id=uuid.uuid4().hex[:12],
            group_id=str(group_id),
            uploader_id=str(uploader_id),
            file_name=_safe_name(file_name) if file_name else "file.bin",
            local_path=local_path or "",
            summary=(summary or "").strip(),
            tags=(tags or "").strip(),
            create_time=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO file_index
                    (id, group_id, uploader_id, file_name, local_path, summary, tags, create_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.group_id,
                        record.uploader_id,
                        record.file_name,
                        record.local_path,
                        record.summary,
                        record.tags,
                        record.create_time,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return record

    def update_summary(self, file_id: str, summary: str, tags: str = "") -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE file_index SET summary=?, tags=? WHERE id=?",
                    ((summary or "").strip(), (tags or "").strip(), file_id),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    @staticmethod
    def _tokens(query: str) -> list[str]:
        """拆查询：整句 + 中文 2-gram + 英文数字词，供模糊打分。"""
        q = (query or "").strip()
        if not q:
            return []
        toks = {q}
        for m in re.finditer(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]{2,}", q):
            w = m.group(0)
            toks.add(w)
            if re.fullmatch(r"[\u4e00-\u9fff]{3,}", w):
                for i in range(len(w) - 1):
                    toks.add(w[i : i + 2])
        # 去停用噪声
        stop = {"一下", "发给", "发我", "那个", "这个", "什么", "文件"}
        return [t for t in toks if t not in stop and len(t) >= 2]

    def search(
        self,
        query: str,
        *,
        group_id: str | None = None,
        limit: int = 5,
    ) -> list[FileRecord]:
        tokens = self._tokens(query)
        if not tokens:
            return []
        sql = "SELECT * FROM file_index WHERE 1=1"
        args: list[Any] = []
        if group_id is not None:
            sql += " AND group_id=?"
            args.append(str(group_id))
        sql += " ORDER BY create_time DESC LIMIT 200"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, args).fetchall()
            finally:
                conn.close()
        scored: list[tuple[int, FileRecord]] = []
        for row in rows:
            rec = self._row(row)
            blob = f"{rec.file_name} {rec.summary} {rec.tags} {rec.uploader_id}"
            score = sum(1 for t in tokens if t in blob)
            if score > 0:
                scored.append((score, rec))
        scored.sort(key=lambda x: (-x[0], x[1].create_time))
        return [r for _, r in scored[:limit]]

    def get(self, file_id: str) -> FileRecord | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM file_index WHERE id=?", (file_id,)
                ).fetchone()
            finally:
                conn.close()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> FileRecord:
        return FileRecord(
            id=row["id"],
            group_id=row["group_id"],
            uploader_id=row["uploader_id"],
            file_name=row["file_name"],
            local_path=row["local_path"] or "",
            summary=row["summary"] or "",
            tags=row["tags"] or "",
            create_time=row["create_time"],
        )


_STORE: FileIndexStore | None = None


def get_file_index() -> FileIndexStore:
    global _STORE
    if _STORE is None:
        _STORE = FileIndexStore()
    return _STORE
