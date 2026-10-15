"""前置拦截：待办 / 退出清会话 / 保存上面的文件 / 文件列表私聊 / 删除确认。

这些路径尽量 0 Token 或仅文件摘要烧一次 Token。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.channel.context import ChatContext
from agent.channel.file_cache import RECENT_FILES
from agent.channel.pending import (
    clear_pending_delete,
    get_pending_delete,
    pop_pending_delete,
    set_pending_delete,
)
from agent.channel.session import SESSIONS, session_key
from agent.files import get_file_index
from agent.files.pipeline import format_ingest_reply, ingest_file_segments
from agent.schedules import get_schedule_store
from agent.schedules.rules import CATEGORY_LABELS

# 用户说退出/清空 → 只清会话，QQ Agent 进程继续跑
_EXIT_RE = re.compile(
    r"^(退出|退出对话|结束|结束对话|清空|清空对话|重置|reset|exit|quit|"
    r"再见|拜拜)[？?！!\s～~]*$",
    re.I,
)

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

# 保存上面的文件（群聊 @）——必须带「上面/刚才/文件」语义，避免误伤「帮我保存到记忆」
_SAVE_ABOVE_RE = re.compile(
    r"(帮我)?(把)?(上面|刚才|上方|前面|上一条|最近).{0,6}(的)?(那个)?(文件|附件|图|图片)?"
    r".{0,6}(保存|存一下|存下|收下|收藏|入库)|"
    r"(帮我)?(保存|存一下|存下|收下).{0,8}(上面|刚才|上方|前面|上一条).{0,6}(文件|附件|图|图片)?|"
    r"帮我保存(上面|刚才)?(的)?(文件|附件)",
    re.I,
)

# 文件列表 → 私聊发送
_FILE_LIST_RE = re.compile(
    r"^(你)?(现在)?(有哪些|有什么|看看|查看|列出|给我看)?(我的|我拥有的|我上传的)?"
    r"(文件|附件)(列表|list)?[？?！!\s～~]*$"
    r"|^(文件列表|我的文件|有哪些文件|现在有哪些文件|我有哪些文件)"
    r"[？?！!\s～~]*$",
    re.I,
)

# 删除某某
_DELETE_RE = re.compile(
    r"^(帮我)?(删除|删掉|去掉|移除)(文件|附件)?\s*(?P<name>.+?)"
    r"[？?！!\s～~]*$",
    re.I,
)
_CONFIRM_RE = re.compile(
    r"^(确认删除|确认|确定|是的|好的|删吧|删除吧|yes|ok)[？?！!\s～~]*$",
    re.I,
)
_CANCEL_RE = re.compile(
    r"^(取消|不要|算了|不删|取消删除|no)[？?！!\s～~]*$",
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

    # —— 删除确认 / 取消 ——
    pending = get_pending_delete(ctx.user_id)
    if pending and _CONFIRM_RE.match(text):
        return _do_confirm_delete(ctx)
    if pending and _CANCEL_RE.match(text):
        clear_pending_delete(ctx.user_id)
        return f"已取消删除 {pending.file_name}"

    # —— 发起删除 ——
    m_del = _DELETE_RE.match(text)
    if m_del:
        name = (m_del.group("name") or "").strip()
        name = re.sub(r"^(文件|附件)\s*", "", name).strip()
        if name and name not in ("这个", "那个", "它"):
            return _ask_delete(ctx, name)

    # —— 文件列表：私聊发 list ——
    if _FILE_LIST_RE.match(text):
        return _send_file_list_private(ctx)

    # —— 保存上面的文件 ——
    if ctx.is_group and ctx.group_id and _SAVE_ABOVE_RE.search(text):
        return _save_above_files(ctx)

    # —— 待办短句 ——
    if not _STATUS_RE.match(text):
        return None

    store = get_schedule_store()
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


def _save_above_files(ctx: ChatContext) -> str:
    from agent.files.pipeline import summarize_file

    gid = ctx.group_id or ""
    recent = RECENT_FILES.recent(
        gid, limit=3, within_seconds=1800, uploader_id=None
    )
    # 优先本人刚发的；没有则取群里最近的
    mine = [x for x in recent if x.uploader_id == ctx.user_id]
    picks = mine[:2] if mine else recent[:1]
    if not picks:
        return "我没看到上面有可保存的文件。请先发文件，再 @ 我说「帮我保存上面的文件」。"

    store = get_file_index()
    # 若静默入库已有同名无摘要记录 → 补摘要，避免重复行
    updated = []
    need_ingest = []
    for item in picks:
        existing = [
            r
            for r in store.list_for_user(ctx.user_id, limit=30)
            if r.group_id == gid and r.file_name == item.name
        ]
        # 也扫本群最近索引（静默入库 uploader 可能是别人）
        if not existing:
            existing = store.search(
                item.name, group_id=gid, limit=5
            )
            existing = [r for r in existing if r.file_name == item.name]
        if existing and not (existing[0].summary or "").strip():
            summary = summarize_file(
                file_name=item.name, group_context=ctx.group_context or ""
            )
            tags = item.name.rsplit(".", 1)[-1] if "." in item.name else ""
            store.update_summary(existing[0].id, summary, tags=tags)
            rec = store.get(existing[0].id)
            if rec:
                updated.append(rec)
        elif existing and (existing[0].summary or "").strip():
            updated.append(existing[0])
        else:
            need_ingest.append(item)

    records = list(updated)
    if need_ingest:
        segments = [RECENT_FILES.to_segment(x) for x in need_ingest]
        records.extend(
            ingest_file_segments(
                segments=segments,
                group_id=gid,
                uploader_id=ctx.user_id,
                summarize=True,
                group_context=ctx.group_context or "",
            )
        )
    ack = format_ingest_reply(records)
    return ack or "已尝试保存，但没有成功落库。"


def _format_user_files(user_id: str) -> str:
    store = get_file_index()
    records = store.list_for_user(user_id, limit=40)
    if not records:
        return "你当前没有已保存的文件。"
    lines = [f"你拥有的文件（共 {len(records)} 条，最新在前）："]
    for i, r in enumerate(records, 1):
        where = "私聊" if r.group_id == "private" else f"群{r.group_id}"
        summary = r.summary or "（无摘要）"
        lines.append(
            f"{i}. [{r.id}] {r.file_name} | {where}\n   摘要：{summary}"
        )
    lines.append("删除可说：删除 文件名（或删除 id）")
    return "\n".join(lines)


def _send_file_list_private(ctx: ChatContext) -> str:
    text = _format_user_files(ctx.user_id)
    from agent.channel.client_ref import get_onebot_client
    from agent.channel.send import safe_send_msg

    client = get_onebot_client()
    if client is None:
        return text  # 降级：当场回复
    ok = safe_send_msg(
        client, user_id=ctx.user_id, message=text, chunk=False
    )
    if ctx.is_group:
        return "已私聊发给你文件列表啦，去看看～" if ok else (
            "私聊发送失败，先在这里贴一份：\n" + text
        )
    return text if ok else ("发送异常，内容如下：\n" + text)


def _ask_delete(ctx: ChatContext, name_query: str) -> str:
    store = get_file_index()
    hits = store.find_by_name(ctx.user_id, name_query, limit=3)
    if not hits:
        return f"没找到你名下叫「{name_query}」的文件。可以说「有哪些文件」看列表。"
    if len(hits) > 1:
        lines = [f"找到多个匹配「{name_query}」，请说更具体的文件名或 id："]
        for h in hits:
            lines.append(
                f"- [{h.id}] {h.file_name}："
                f"{h.summary or '（无摘要）'}"
            )
        return "\n".join(lines)

    rec = hits[0]
    set_pending_delete(
        user_id=ctx.user_id,
        file_id=rec.id,
        file_name=rec.file_name,
        summary=rec.summary or "",
        local_path=rec.local_path or "",
    )
    purpose = rec.summary or "（当时未写摘要，仅按文件名保存）"
    where = "私聊" if rec.group_id == "private" else f"群{rec.group_id}"
    return (
        f"即将删除：{rec.file_name} [{rec.id}]\n"
        f"来源：{where}\n"
        f"这个文件是干什么的：{purpose}\n"
        f"确认删除请回复「确认删除」，取消请回「取消」。"
    )


def _do_confirm_delete(ctx: ChatContext) -> str:
    pending = pop_pending_delete(ctx.user_id)
    if not pending:
        return "没有待确认的删除。可以说「删除 文件名」。"

    # 沙箱直删（无索引 id）
    if pending.file_id.startswith("sandbox:"):
        from agent.user_files import delete_file as sandbox_delete

        name = pending.file_name
        ok = sandbox_delete(ctx.user_id, name, None) or sandbox_delete(
            ctx.user_id, name, ctx.recall_group_id
        )
        return f"已删除 {name}" if ok else f"删除失败：找不到 {name}"

    store = get_file_index()
    deleted = store.delete(pending.file_id, user_id=ctx.user_id)
    if not deleted:
        if pending.local_path:
            try:
                p = Path(pending.local_path)
                if p.is_file():
                    p.unlink()
                    return f"已删除本地文件 {pending.file_name}"
            except Exception:
                pass
        return f"索引里已找不到 {pending.file_name}，可能已被删。"
    return f"已删除 {deleted.file_name}（{deleted.summary or '无摘要'}）"


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
