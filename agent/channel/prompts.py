"""系统提示：隔离 + 记忆预召回 + 群聊滑动窗口。

工具面只暴露 QQ 能力；鼓励轻微表情；不提 bash / edit / Task DAG。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.channel.context import ChatContext
from agent.knowledge import get_knowledge_store
from agent.schedules import get_schedule_store

SYSTEM_BASE = """你是挂在 QQ 上的干活型助手（自研 Agent Loop）。
能力：
1. 记忆 save_memory / get_memory / delete_memory（也可 kb_add / remember / recall）
2. 催办 schedule_reminder（或 schedule_create）/ schedule_list / done / cancel
   - category：exam / meeting / activity / todo
   - 考试：提前一周 + 隔两天 + 提前5小时/2小时 + 提前10分钟
   - 会议/活动/待办：隔两天 + 提前1天/5小时/2小时 + 提前10分钟
3. 群文件索引：用户 @+发文件时已自动摘要入库；用 search_and_send_file 按摘要/文件名找回并发出
   另有 download_file / list_files / send_local_file / delete_file
4. web_search 联网搜索

规则：
- 每人记忆与任务相互隔离；群聊任务/文件挂在当前群作用域
- 下方「最近的群聊记录」仅作背景理解，不要逐条回复灌水
- 创建催办：用当前时间把相对时间换成 ISO8601（+08:00），选对 category，一次 schedule_reminder
- 禁止为催办反复查时间；催办本地定时，0 Token
- 长期记忆只在用户明确要求「记住」或确属个人偏好时写入 save_memory
- 用户说「把XX发我 / 简历 / 那个文件」→ 优先 search_and_send_file
- 没有写码/改文件/跑 shell 能力；不要假装能执行 bash 或改仓库
- 回复简洁适合 QQ；偶尔带上合适的 QQ 表情，如 [微笑]、[捂脸]、[OK]（不要每句都带）
- 用户说「退出/再见」只表示结束本轮对话；你无法也不要尝试关闭机器人进程
"""


def build_system_prompt(ctx: ChatContext) -> str:
    who = f"当前用户 QQ={ctx.user_id}"
    if ctx.nickname:
        who += f" 昵称={ctx.nickname}"

    if ctx.is_group:
        scope = f"场景：群聊 group_id={ctx.group_id}（仅当被 @ 才处理）"
        if ctx.group_name:
            scope += f" group_name={ctx.group_name}"
    else:
        scope = "场景：私聊（默认真对你说话）"

    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(tz8)
    weekday = "一二三四五六日"[now.weekday()]
    now_line = (
        f"当前时间（必须用于换算相对时间）："
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{weekday}（UTC+8）"
    )

    if ctx.group_context:
        group_block = (
            "最近的群聊记录（供理解背景，不必全部回复）：\n" + ctx.group_context
        )
    else:
        group_block = "最近的群聊记录：（无）"

    hits = get_knowledge_store().kb_search(
        user_id=ctx.user_id,
        query=(ctx.text or "最近记录")[:200],
        group_id=ctx.recall_group_id,
        top_k=3,
    )
    if hits:
        lines = []
        for record, score in hits:
            where = f"群{record.group_id}" if record.group_id != "private" else "私聊"
            title = f"{record.title} | " if record.title else ""
            lines.append(
                f"- [{record.id}] ({record.kind}, {where}, {score:.2f}) "
                f"{title}{record.text}"
            )
        kb_block = "可能相关的记忆：\n" + "\n".join(lines)
    else:
        kb_block = "可能相关的记忆：（暂无）"

    upcoming = get_schedule_store().list_for_user(
        user_id=ctx.user_id,
        group_id=ctx.recall_group_id if ctx.is_group else None,
        tasks_only=True,
    )[:5]
    if upcoming:
        slines = [
            f"- [{s.id}] ({s.category}) {s.status} {s.title} due={s.due_at}"
            for s in upcoming
        ]
        sched_block = "任务列表预览：\n" + "\n".join(slines)
    else:
        sched_block = "任务列表预览：（暂无）"

    return (
        f"{SYSTEM_BASE}\n{who}\n{scope}\n{now_line}\n\n"
        f"{group_block}\n\n{kb_block}\n\n{sched_block}"
    )
