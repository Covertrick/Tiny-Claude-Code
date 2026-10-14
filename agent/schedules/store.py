"""行程 / 催办持久化：SQLite；任务 list + 多点催办。"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.config import SCHEDULES_DB, ensure_runtime_dirs
from agent.schedules.rules import normalize_category, plan_reminder_times


@dataclass
class ScheduleRecord:
    id: str
    user_id: str
    group_id: str
    title: str
    due_at: str
    remind_at: str
    status: str  # pending / reminded / done / cancelled
    created_at: str
    channel: str
    category: str = "todo"
    parent_id: str = ""
    role: str = "task"  # task | tick
    label: str = ""


class ScheduleStore:
    def __init__(self, db_path: Path | None = None):
        ensure_runtime_dirs()
        self.db_path = db_path or SCHEDULES_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                    CREATE TABLE IF NOT EXISTS schedules (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        group_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        due_at TEXT NOT NULL,
                        remind_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'todo',
                        parent_id TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL DEFAULT 'task',
                        label TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cols = {
                    r[1]
                    for r in conn.execute("PRAGMA table_info(schedules)").fetchall()
                }
                for name, decl in (
                    ("category", "TEXT NOT NULL DEFAULT 'todo'"),
                    ("parent_id", "TEXT NOT NULL DEFAULT ''"),
                    ("role", "TEXT NOT NULL DEFAULT 'task'"),
                    ("label", "TEXT NOT NULL DEFAULT ''"),
                ):
                    if name not in cols:
                        conn.execute(f"ALTER TABLE schedules ADD COLUMN {name} {decl}")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sched_remind "
                    "ON schedules(status, remind_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sched_parent "
                    "ON schedules(parent_id)"
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ScheduleRecord:
        keys = row.keys()
        return ScheduleRecord(
            id=row["id"],
            user_id=row["user_id"],
            group_id=row["group_id"],
            title=row["title"],
            due_at=row["due_at"],
            remind_at=row["remind_at"],
            status=row["status"],
            created_at=row["created_at"],
            channel=row["channel"],
            category=row["category"] if "category" in keys else "todo",
            parent_id=row["parent_id"] if "parent_id" in keys else "",
            role=row["role"] if "role" in keys else "task",
            label=row["label"] if "label" in keys else "",
        )

    def _insert(self, conn: sqlite3.Connection, record: ScheduleRecord) -> None:
        conn.execute(
            """
            INSERT INTO schedules
            (id, user_id, group_id, title, due_at, remind_at, status, created_at,
             channel, category, parent_id, role, label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.user_id,
                record.group_id,
                record.title,
                record.due_at,
                record.remind_at,
                record.status,
                record.created_at,
                record.channel,
                record.category,
                record.parent_id,
                record.role,
                record.label,
            ),
        )

    def create_task_with_reminders(
        self,
        *,
        user_id: str,
        group_id: str,
        title: str,
        due_at: str,
        category: str = "todo",
        channel: str = "private",
    ) -> tuple[ScheduleRecord, list[ScheduleRecord]]:
        """创建任务 + 按类别展开的多点催办；返回 (任务, 催办列表含到点)。"""
        title = (title or "").strip()
        if not title:
            raise ValueError("行程标题不能为空")
        category = normalize_category(category)
        due_iso = _normalize_iso(due_at)
        due_dt = datetime.fromisoformat(due_iso)
        channel = channel if channel in ("private", "group") else "private"
        now = datetime.now(timezone.utc)
        created = now.isoformat()
        plan = plan_reminder_times(category=category, due_at=due_dt, now=now)
        if not plan:
            plan = [("到点", due_dt)]

        parent_id = uuid.uuid4().hex[:10]
        parent = ScheduleRecord(
            id=parent_id,
            user_id=str(user_id),
            group_id=str(group_id or "private"),
            title=title,
            due_at=due_iso,
            remind_at=due_iso,
            status="pending",
            created_at=created,
            channel=channel,
            category=category,
            parent_id="",
            role="task",
            label="",
        )
        ticks: list[ScheduleRecord] = []
        for label, when in plan:
            ticks.append(
                ScheduleRecord(
                    id=uuid.uuid4().hex[:10],
                    user_id=parent.user_id,
                    group_id=parent.group_id,
                    title=title,
                    due_at=due_iso,
                    remind_at=when.isoformat(),
                    status="pending",
                    created_at=created,
                    channel=channel,
                    category=category,
                    parent_id=parent_id,
                    role="tick",
                    label=label,
                )
            )

        with self._lock:
            conn = self._connect()
            try:
                self._insert(conn, parent)
                for t in ticks:
                    self._insert(conn, t)
                conn.commit()
            finally:
                conn.close()
        return parent, ticks

    def create(
        self,
        *,
        user_id: str,
        group_id: str,
        title: str,
        due_at: str,
        remind_at: str | None = None,
        channel: str = "private",
        category: str = "todo",
    ) -> ScheduleRecord:
        """兼容旧接口：单点催办；内部仍走多点规则（忽略自定义 remind_at）。"""
        parent, _ticks = self.create_task_with_reminders(
            user_id=user_id,
            group_id=group_id,
            title=title,
            due_at=due_at,
            category=category,
            channel=channel,
        )
        return parent

    def list_for_user(
        self,
        *,
        user_id: str,
        group_id: str | None = None,
        include_done: bool = False,
        tasks_only: bool = False,
    ) -> list[ScheduleRecord]:
        sql = "SELECT * FROM schedules WHERE user_id = ?"
        params: list[str] = [str(user_id)]
        if group_id is not None:
            sql += " AND group_id = ?"
            params.append(str(group_id))
        if tasks_only:
            sql += " AND role = 'task'"
        if not include_done:
            sql += " AND status IN ('pending', 'reminded')"
        sql += " ORDER BY due_at ASC, remind_at ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_record(r) for r in rows]
            finally:
                conn.close()

    def list_ticks(self, parent_id: str) -> list[ScheduleRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM schedules WHERE parent_id = ? ORDER BY remind_at ASC",
                    (parent_id,),
                ).fetchall()
                return [self._row_to_record(r) for r in rows]
            finally:
                conn.close()

    def set_status(self, *, user_id: str, schedule_id: str, status: str) -> bool:
        if status not in ("pending", "reminded", "done", "cancelled"):
            raise ValueError(f"非法状态: {status}")
        with self._lock:
            conn = self._connect()
            try:
                rec = conn.execute(
                    "SELECT * FROM schedules WHERE id = ? AND user_id = ?",
                    (schedule_id, str(user_id)),
                ).fetchone()
                if not rec:
                    return False
                record = self._row_to_record(rec)
                # 完成/取消任务时，同步所有催办点
                if record.role == "task" and status in ("done", "cancelled"):
                    conn.execute(
                        "UPDATE schedules SET status = ? WHERE user_id = ? AND "
                        "(id = ? OR parent_id = ?)",
                        (status, str(user_id), schedule_id, schedule_id),
                    )
                else:
                    conn.execute(
                        "UPDATE schedules SET status = ? WHERE id = ? AND user_id = ?",
                        (status, schedule_id, str(user_id)),
                    )
                conn.commit()
                return True
            finally:
                conn.close()

    def child_ids(self, parent_id: str) -> list[str]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT id FROM schedules WHERE parent_id = ?",
                    (parent_id,),
                ).fetchall()
                return [r["id"] for r in rows]
            finally:
                conn.close()

    def due_pending(self, *, now_iso: str | None = None) -> list[ScheduleRecord]:
        now = now_iso or datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM schedules
                    WHERE status = 'pending' AND role = 'tick' AND remind_at <= ?
                    ORDER BY remind_at ASC
                    LIMIT 50
                    """,
                    (now,),
                ).fetchall()
                return [self._row_to_record(r) for r in rows]
            finally:
                conn.close()

    def pending_within(
        self,
        *,
        hours: float = 24,
        now: datetime | None = None,
    ) -> list[ScheduleRecord]:
        from datetime import timedelta

        now = now or datetime.now(timezone.utc)
        end = now + timedelta(hours=hours)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM schedules
                    WHERE status = 'pending' AND role = 'tick' AND remind_at <= ?
                    ORDER BY remind_at ASC
                    LIMIT 500
                    """,
                    (end.isoformat(),),
                ).fetchall()
                return [self._row_to_record(r) for r in rows]
            finally:
                conn.close()

    def get(self, schedule_id: str) -> ScheduleRecord | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM schedules WHERE id = ?",
                    (schedule_id,),
                ).fetchone()
                return self._row_to_record(row) if row else None
            finally:
                conn.close()

    def mark_reminded(self, schedule_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE schedules SET status = 'reminded' "
                    "WHERE id = ? AND status = 'pending'",
                    (schedule_id,),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()


def _normalize_iso(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("时间不能为空")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as e:
        raise ValueError(
            f"时间格式无效，请用 ISO8601，例如 2026-10-15T15:00:00+08:00: {value}"
        ) from e
    if dt.tzinfo is None:
        from datetime import timedelta

        dt = dt.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


_STORE: ScheduleStore | None = None


def get_schedule_store() -> ScheduleStore:
    global _STORE
    if _STORE is None:
        _STORE = ScheduleStore()
    return _STORE
