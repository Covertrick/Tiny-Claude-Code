"""主动智能：每日早报（0 Token）+ 群关键词私聊提醒（0 Token）。"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger

from agent.config import (
    ALERT_KEYWORDS,
    KEYWORD_ALERT_COOLDOWN,
    MORNING_BRIEF_HOUR,
    MORNING_BRIEF_MINUTE,
    OWNER_QQ,
)
from agent.schedules import get_schedule_store
from agent.schedules.rules import CATEGORY_LABELS

if TYPE_CHECKING:
    from agent.channel.onebot import OneBotClient
    from agent.scheduler import ReminderScheduler


class KeywordWatcher:
    """后台正则监控群聊文本；命中则私聊主人。"""

    def __init__(self, client: OneBotClient):
        self.client = client
        self._patterns = [
            re.compile(re.escape(k), re.I) for k in ALERT_KEYWORDS if k
        ]
        self._cooldown: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_group_text(
        self, *, group_id: str, user: str, text: str
    ) -> None:
        if not self._patterns or not OWNER_QQ or not text:
            return
        hit = None
        for pat in self._patterns:
            m = pat.search(text)
            if m:
                hit = m.group(0)
                break
        if not hit:
            return
        key = f"{group_id}:{hit}"
        now = time.time()
        with self._lock:
            last = self._cooldown.get(key, 0)
            if now - last < KEYWORD_ALERT_COOLDOWN:
                return
            self._cooldown[key] = now
        msg = (
            f"群里有提到「{hit}」，快去看看\n"
            f"群={group_id} | 发言人={user}\n"
            f"原文：{text[:200]}"
        )
        try:
            from agent.channel.send import safe_send_msg

            safe_send_msg(
                self.client, user_id=OWNER_QQ, message=msg, chunk=False
            )
            print(f"[keyword] 告警「{hit}」→ 主人 {OWNER_QQ}")
        except Exception as e:
            print(f"[keyword] 发送失败: {e}")


def build_morning_brief(owner_qq: str | None = None) -> str:
    """查 SQLite 待办，拼早报文本（不经 LLM）。"""
    uid = owner_qq or OWNER_QQ
    if not uid:
        return ""
    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(tz8)
    today = now.date()
    store = get_schedule_store()
    tasks = store.list_for_user(user_id=uid, tasks_only=True)
    today_items = []
    for t in tasks:
        if t.status not in ("pending", "reminded"):
            continue
        try:
            due = datetime.fromisoformat(t.due_at)
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            due_local = due.astimezone(tz8)
        except Exception:
            continue
        if due_local.date() == today:
            today_items.append((due_local, t))
    today_items.sort(key=lambda x: x[0])
    lines = [
        f"☀️ 早报 {now.strftime('%Y-%m-%d')} 星期"
        f"{'一二三四五六日'[now.weekday()]}",
        "",
    ]
    if today_items:
        lines.append("今日待办：")
        for due_local, t in today_items:
            cat = CATEGORY_LABELS.get(t.category, t.category)
            lines.append(
                f"· [{cat}] {t.title} @ {due_local.strftime('%H:%M')}"
            )
    else:
        lines.append("今日待办：（空）")
    rest = len(tasks) - len(today_items)
    if rest > 0:
        lines.append("")
        lines.append(f"其余未完成任务共 {rest} 条（问「待办事项」查看）")
    return "\n".join(lines)


def register_morning_brief(scheduler: ReminderScheduler) -> None:
    """挂到现有 APScheduler：每天早上私聊主人。"""
    if not OWNER_QQ:
        print("[morning] 未配置 QQ_OWNER_QQ，跳过每日早报")
        return

    def _job() -> None:
        try:
            text = build_morning_brief(OWNER_QQ)
            if not text:
                return
            from agent.channel.send import safe_send_msg

            safe_send_msg(
                scheduler.client,
                user_id=OWNER_QQ,
                message=text,
                chunk=False,
            )
            print(f"[morning] 已推送早报 → {OWNER_QQ}")
        except Exception as e:
            print(f"[morning] 失败: {e}")

    scheduler._aps.add_job(
        _job,
        CronTrigger(
            hour=MORNING_BRIEF_HOUR,
            minute=MORNING_BRIEF_MINUTE,
            timezone="Asia/Shanghai",
        ),
        id="morning_brief",
        replace_existing=True,
        max_instances=1,
    )
    print(
        f"[morning] 每日早报已注册 "
        f"{MORNING_BRIEF_HOUR:02d}:{MORNING_BRIEF_MINUTE:02d} → {OWNER_QQ}"
    )
