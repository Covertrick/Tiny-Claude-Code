"""分层催办：粗粒度装载 + APScheduler DateTrigger 精确到秒（不经 LLM）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.config import SCHEDULE_HORIZON_HOURS, SCHEDULE_RELOAD_MINUTES
from agent.schedules import ScheduleRecord, get_schedule_store
from agent.timeutil import TZ_SHANGHAI, ensure_aware_utc, now_utc

if TYPE_CHECKING:
    from agent.channel.onebot import OneBotClient

_JOB_PREFIX = "sched_"


class ReminderScheduler:
    def __init__(
        self,
        client: OneBotClient,
        *,
        horizon_hours: int | None = None,
        reload_minutes: int | None = None,
    ):
        self.client = client
        self.horizon_hours = horizon_hours or SCHEDULE_HORIZON_HOURS
        self.reload_minutes = reload_minutes or SCHEDULE_RELOAD_MINUTES
        # 调度器以上海时区理解 cron；落库/比较一律 UTC aware
        self._aps = BackgroundScheduler(timezone=TZ_SHANGHAI)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._aps.add_job(
            self.reload_upcoming,
            IntervalTrigger(minutes=self.reload_minutes),
            id="coarse_reload",
            replace_existing=True,
            max_instances=1,
        )
        self._aps.start()
        self._started = True
        self.reload_upcoming()
        print(
            f"[scheduler] APScheduler 已启动："
            f"精确 DateTrigger + 每 {self.reload_minutes} 分钟装载未来 "
            f"{self.horizon_hours}h 任务"
        )

    def stop(self) -> None:
        if self._started:
            self._aps.shutdown(wait=False)
            self._started = False

    def arm(self, record: ScheduleRecord) -> None:
        """创建行程后立即注册（若在 horizon 内或已过期）。"""
        if not self._started:
            return
        if record.status != "pending":
            return
        remind = ensure_aware_utc(datetime.fromisoformat(record.remind_at))
        now = now_utc()
        from datetime import timedelta

        if remind > now + timedelta(hours=self.horizon_hours):
            print(f"[scheduler] 长期任务 id={record.id} 暂不装载，等粗粒度扫描")
            return
        self._schedule_fire(record.id, remind)

    def disarm(self, schedule_id: str) -> None:
        job_id = f"{_JOB_PREFIX}{schedule_id}"
        try:
            self._aps.remove_job(job_id)
        except Exception:
            pass

    def reload_upcoming(self) -> None:
        store = get_schedule_store()
        items = store.pending_within(hours=self.horizon_hours)
        now = now_utc()
        loaded = 0
        for item in items:
            remind = ensure_aware_utc(datetime.fromisoformat(item.remind_at))
            # 已过期：立刻触发（DateTrigger 用 now）
            run_at = remind if remind > now else now
            self._schedule_fire(item.id, run_at)
            loaded += 1
        print(f"[scheduler] 粗粒度装载 {loaded} 条（horizon={self.horizon_hours}h）")

    def _schedule_fire(self, schedule_id: str, run_at: datetime) -> None:
        job_id = f"{_JOB_PREFIX}{schedule_id}"
        # APScheduler 用上海时区；传入 aware UTC 会自动换算
        self._aps.add_job(
            self._fire,
            DateTrigger(run_date=ensure_aware_utc(run_at)),
            id=job_id,
            args=[schedule_id],
            replace_existing=True,
            misfire_grace_time=300,
        )

    def _fire(self, schedule_id: str) -> None:
        store = get_schedule_store()
        item = store.get(schedule_id)
        if item is None or item.status != "pending":
            return
        if not store.mark_reminded(schedule_id):
            return
        from agent.schedules.rules import CATEGORY_LABELS

        cat = CATEGORY_LABELS.get(item.category, item.category)
        label = item.label or "提醒"
        task_id = item.parent_id or item.id
        msg = (
            f"⏰ 【{label}】{item.title}\n"
            f"类型：{cat} | 任务id={task_id}\n"
            f"看全部待办可回：待办事项"
        )
        from agent.channel.send import safe_send_msg

        try:
            if item.channel == "group" and item.group_id != "private":
                payload = [
                    {"type": "at", "data": {"qq": str(item.user_id)}},
                    {"type": "text", "data": {"text": f" {msg}"}},
                ]
                ok = safe_send_msg(
                    self.client,
                    group_id=item.group_id,
                    message=payload,
                    chunk=False,
                )
            else:
                ok = safe_send_msg(
                    self.client,
                    user_id=item.user_id,
                    message=msg,
                    chunk=False,
                )
            if not ok:
                raise RuntimeError("safe_send 失败")
            print(
                f"[scheduler] 精确催办 id={item.id} user={item.user_id} "
                f"title={item.title}"
            )
        except Exception as e:
            store.set_status(
                user_id=item.user_id, schedule_id=item.id, status="pending"
            )
            print(f"[scheduler] 催办发送失败 id={item.id}: {e}")
            self.arm(store.get(schedule_id) or item)


_INSTANCE: ReminderScheduler | None = None


def get_reminder_scheduler() -> ReminderScheduler | None:
    return _INSTANCE


def set_reminder_scheduler(sched: ReminderScheduler | None) -> None:
    global _INSTANCE
    _INSTANCE = sched
