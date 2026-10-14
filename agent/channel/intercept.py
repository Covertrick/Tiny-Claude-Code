"""前置拦截：待办短句 / 退出清空会话（永不杀进程）。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from agent.channel.context import ChatContext
from agent.channel.session import SESSIONS, session_key
from agent.schedules import get_schedule_store
from agent.schedules.rules import CATEGORY_LABELS

# 用户说退出/清空 → 只清会话，QQ Agent 进程继续跑
_EXIT_RE = re.compile(
    r"^(退出|退出对话|结束|结束对话|清空|清空对话|重置|reset|exit|quit|"
    r"再见|拜拜)[？?！!\s～~]*$",
    re.I,
)

# 命中则不进 Agent
_STATUS_RE = re.compile(
    r"^(到了没|到了吗|到了嘛|还有多久|多久了|进度怎么样|进度|我的日程|查看日程|"
    r"有哪些行程|行程列表|还有几个任务|提醒到了没|待办事项|我的待办|待办列表|"
    r"任务列表|有哪些待办)[？?！!\s]*$",
    re.I,
)
_LIST_RE = re.compile(
    r"(我的日程|查看日程|有哪些行程|行程列表|还有几个任务|待办事项|我的待办|"
    r"待办列表|任务列表|有哪些待办)",
    re.I,
)


def try_intercept(ctx: ChatContext) -> str | None:
    text = (ctx.text or "").strip()
    if not text:
        return None

    if _EXIT_RE.match(text):
        key = session_key(
            user_id=ctx.user_id, group_id=ctx.group_id, is_group=ctx.is_group
        )
        SESSIONS.clear(key)
        return "好，本会话已清空。我还在线，随时叫我～（不会关机器人）"

    if not _STATUS_RE.match(text):
        return None

    store = get_schedule_store()
    # 用户要的是任务 list，不是每次催办子点
    tasks = store.list_for_user(
        user_id=ctx.user_id,
        group_id=ctx.recall_group_id if ctx.is_group else None,
        tasks_only=True,
    )
    if not tasks:
        return "待办事项 list：（空）\n可以说「三天后开会，会议类提醒我」来添加。"

    now = datetime.now(timezone.utc)
    lines = ["待办事项 list（本地查询，未走大模型）："]
    for i, s in enumerate(tasks[:20], 1):
        due = datetime.fromisoformat(s.due_at)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        delta = due - now
        if s.status == "reminded":
            eta = "已催过，可说完成"
        elif delta.total_seconds() <= 0:
            eta = "已到期"
        else:
            eta = "剩余 " + _fmt_delta(delta)
        local = due.astimezone(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
        cat = CATEGORY_LABELS.get(s.category, s.category)
        lines.append(
            f"{i}. [{s.id}] [{cat}] {s.title} | 到期 {local} | {eta} | {s.status}"
        )

    if not _LIST_RE.search(text):
        # 「到了没」类：附带下一次催办
        ticks = []
        for t in tasks[:5]:
            for tick in store.list_ticks(t.id):
                if tick.status == "pending":
                    ticks.append(tick)
                    break
        if ticks:
            lines.append("下次催办：")
            for tick in ticks[:5]:
                rt = datetime.fromisoformat(tick.remind_at)
                if rt.tzinfo is None:
                    rt = rt.replace(tzinfo=timezone.utc)
                local = rt.astimezone(timezone(timedelta(hours=8))).strftime(
                    "%m-%d %H:%M"
                )
                lines.append(f"  · {tick.title} — {tick.label} @ {local}")

    lines.append("完成可说「完成任务 id=xxx」；取消可说「取消任务 id=xxx」。")
    return "\n".join(lines)


def _fmt_delta(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}秒"
    mins, sec = divmod(secs, 60)
    if mins < 60:
        return f"{mins}分{sec}秒" if sec else f"{mins}分钟"
    hours, mins = divmod(mins, 60)
    if hours < 48:
        return f"{hours}小时{mins}分"
    days, hours = divmod(hours, 24)
    return f"{days}天{hours}小时"
