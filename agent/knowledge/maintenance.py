"""记忆维护：遗忘归档 + 增量知识卡片归纳（挂到 APScheduler）。"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.knowledge import get_knowledge_store


def run_memory_maintenance() -> None:
    store = get_knowledge_store()
    archived = store.archive_stale(max_age_days=21, min_access=1)
    consolidated = store.consolidate_all(min_episodic=3)
    print(
        f"[memory] 维护完成 archived={archived} synthesized_users={consolidated}"
    )


def register_memory_jobs(scheduler) -> None:
    """挂到 ReminderScheduler._aps。"""
    aps = getattr(scheduler, "_aps", None)
    if aps is None:
        return
    aps.add_job(
        run_memory_maintenance,
        IntervalTrigger(hours=6),
        id="memory_maintenance",
        replace_existing=True,
        max_instances=1,
    )
    aps.add_job(
        run_memory_maintenance,
        CronTrigger(hour=3, minute=30, timezone="Asia/Shanghai"),
        id="memory_maintenance_nightly",
        replace_existing=True,
        max_instances=1,
    )
    print("[memory] 已注册维护任务：每 6 小时 + 每天 03:30（增量卡片归纳）")
