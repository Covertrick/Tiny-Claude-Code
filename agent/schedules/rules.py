"""按类别生成多点催办时间表（不耗 Token，纯本地计算）。

- exam：提前 1 周 + 隔 2 天 + 提前 5 小时 / 2 小时 + 提前 10 分钟
- meeting / activity / todo：隔 2 天 + 提前 1 天 / 5 小时 / 2 小时 + 提前 10 分钟

说明：最终一催用「提前 10 分钟」代替整点「到点」，避免考完/开完会才响。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

CATEGORIES = ("exam", "meeting", "activity", "todo")
CATEGORY_LABELS = {
    "exam": "考试",
    "meeting": "会议",
    "activity": "活动",
    "todo": "待办",
}


def normalize_category(value: str | None) -> str:
    v = (value or "todo").strip().lower()
    aliases = {
        "考试": "exam",
        "会议": "meeting",
        "活动": "activity",
        "待办": "todo",
        "任务": "todo",
    }
    v = aliases.get(v, v)
    return v if v in CATEGORIES else "todo"


def plan_reminder_times(
    *,
    category: str,
    due_at: datetime,
    now: datetime | None = None,
) -> list[tuple[str, datetime]]:
    """返回 [(标签, 提醒时刻 UTC), ...]，去重排序，且不早于 now。"""
    category = normalize_category(category)
    now = now or datetime.now(timezone.utc)
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    else:
        due_at = due_at.astimezone(timezone.utc)

    bucket: dict[str, tuple[str, datetime]] = {}

    def add(label: str, dt: datetime) -> None:
        dt = dt.replace(microsecond=0)
        if dt <= now:
            return
        key = dt.strftime("%Y-%m-%dT%H:%M")
        prev = bucket.get(key)
        if prev is None or _label_priority(label) >= _label_priority(prev[0]):
            bucket[key] = (label, dt)

    # 每隔 2 天（通用）
    cursor = due_at - timedelta(days=2)
    while cursor > now:
        add("隔两天提醒", cursor)
        cursor -= timedelta(days=2)

    if category == "exam":
        add("提前一周", due_at - timedelta(days=7))
        cursor = due_at - timedelta(days=7)
        while cursor < due_at - timedelta(minutes=10):
            add("隔两天提醒", cursor)
            cursor += timedelta(days=2)
        add("提前5小时", due_at - timedelta(hours=5))
        add("提前2小时", due_at - timedelta(hours=2))
    else:
        add("提前一天", due_at - timedelta(days=1))
        add("提前5小时", due_at - timedelta(hours=5))
        add("提前2小时", due_at - timedelta(hours=2))

    # 用提前 10 分钟替代整点「到点」
    add("提前10分钟", due_at - timedelta(minutes=10))

    return sorted(bucket.values(), key=lambda x: x[1])


def _label_priority(label: str) -> int:
    order = {
        "提前10分钟": 100,
        "提前2小时": 90,
        "提前5小时": 80,
        "提前一天": 70,
        "提前一周": 60,
        "隔两天提醒": 10,
    }
    return order.get(label, 0)
