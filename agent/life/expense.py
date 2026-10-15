"""轻量记账：正则抽金额，按天窗口统计。"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agent.config import QQ_RUNTIME, ensure_runtime_dirs
from agent.timeutil import TZ_SHANGHAI, now_shanghai

_EXPENSE_RE = re.compile(
    r"(?P<item>.{0,24}?)(?:花了|消费|支出|付了)?\s*(?P<amount>\d+(?:\.\d{1,2})?)\s*(?:元|块|块钱|￥|¥)",
    re.I,
)
_CAT = [
    ("餐饮", re.compile(r"吃|饭|面|餐|咖啡|奶茶|午饭|晚饭|早餐", re.I)),
    ("交通", re.compile(r"打车|地铁|公交|滴滴|火车|机票|出租", re.I)),
    ("娱乐", re.compile(r"电影|游戏|唱K|演出", re.I)),
    ("购物", re.compile(r"买|淘宝|京东|拼多多", re.I)),
]

_LOCK = threading.Lock()
_DB = QQ_RUNTIME / "expenses.db"


@dataclass
class Expense:
    id: int
    user_id: str
    amount: float
    category: str
    note: str
    created_at: str


def _conn() -> sqlite3.Connection:
    ensure_runtime_dirs()
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _category(text: str) -> str:
    for label, pat in _CAT:
        if pat.search(text):
            return label
    return "其他"


def parse_expense(text: str) -> tuple[float, str, str] | None:
    m = _EXPENSE_RE.search(text or "")
    if not m:
        return None
    amount = float(m.group("amount"))
    note = (m.group("item") or text).strip()[:80] or "消费"
    note = re.sub(r"(花了|消费|支出|付了)\s*$", "", note).strip() or "消费"
    return amount, _category(text), note


def add_expense(*, user_id: str, text: str) -> Expense | None:
    parsed = parse_expense(text)
    if not parsed:
        return None
    amount, category, note = parsed
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        conn = _conn()
        try:
            cur = conn.execute(
                "INSERT INTO expenses(user_id, amount, category, note, created_at) "
                "VALUES (?,?,?,?,?)",
                (str(user_id), amount, category, note, now),
            )
            conn.commit()
            eid = int(cur.lastrowid)
        finally:
            conn.close()
    return Expense(
        id=eid,
        user_id=str(user_id),
        amount=amount,
        category=category,
        note=note,
        created_at=now,
    )


def _days_from_text(text: str) -> int:
    if re.search(r"今天|今日", text):
        return 1
    if re.search(r"本周|这周|一周", text):
        return 7
    if re.search(r"本月|这个月|月", text):
        return 31
    return 7


def summarize_expenses(*, user_id: str, days: int | None = None, text: str = "") -> str:
    days = days if days is not None else _days_from_text(text)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    cutoff_iso = cutoff.isoformat()
    with _LOCK:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT category, SUM(amount) AS s, COUNT(*) AS c FROM expenses "
                "WHERE user_id=? AND created_at>=? GROUP BY category ORDER BY s DESC",
                (str(user_id), cutoff_iso),
            ).fetchall()
            total = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM expenses "
                "WHERE user_id=? AND created_at>=?",
                (str(user_id), cutoff_iso),
            ).fetchone()[0]
            recent = conn.execute(
                "SELECT note, amount, category, created_at FROM expenses "
                "WHERE user_id=? AND created_at>=? ORDER BY id DESC LIMIT 5",
                (str(user_id), cutoff_iso),
            ).fetchall()
        finally:
            conn.close()
    label = {1: "今天", 7: "近7天", 31: "近一个月"}.get(days, f"近{days}天")
    if not rows:
        return f"{label}还没有记账。可以说「午饭 25 元」。"
    lines = [f"{label}消费合计约 {float(total):.2f} 元："]
    for r in rows:
        lines.append(f"- {r['category']}：{float(r['s']):.2f} 元（{r['c']} 笔）")
    if recent:
        lines.append("最近几笔：")
        for r in recent:
            try:
                dt = datetime.fromisoformat(r["created_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local = dt.astimezone(TZ_SHANGHAI).strftime("%m-%d %H:%M")
            except Exception:
                local = "?"
            lines.append(
                f"  · {local} {r['note']} {float(r['amount']):.2f}（{r['category']}）"
            )
    return "\n".join(lines)


def list_recent(*, user_id: str, limit: int = 10) -> str:
    with _LOCK:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT id, note, amount, category, created_at FROM expenses "
                "WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (str(user_id), limit),
            ).fetchall()
        finally:
            conn.close()
    if not rows:
        return "账单空空。"
    lines = ["最近账单："]
    for r in rows:
        lines.append(
            f"- [{r['id']}] {r['note']} {float(r['amount']):.2f} 元（{r['category']}）"
        )
    return "\n".join(lines)
