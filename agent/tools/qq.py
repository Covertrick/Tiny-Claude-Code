"""QQ 场景工具面（绞杀边界）：仅搜索 / 记忆 / 催办 / 文件。

故意不包含 Coding 侧 bash / edit / Task DAG / MCP / todo_write。
依赖方向：channel → core → tools.qq → knowledge|schedules|user_files。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from agent.channel.context import ChatContext
from agent.knowledge import get_knowledge_store
from agent.schedules import get_schedule_store
from agent.schedules.rules import CATEGORY_LABELS
from agent.search import fetch_url, web_search
from agent.user_files import download_url, list_all_files, list_files

# QQ 路径白名单：冒烟/文档可对照，禁止混入 coding 工具
QQ_TOOL_NAMES = frozenset(
    {
        "web_search",
        "fetch_url",
        "save_memory",
        "get_memory",
        "delete_memory",
        "synthesize_knowledge",
        "list_knowledge_cards",
        "schedule_reminder",
        "schedule_list",
        "schedule_done",
        "schedule_cancel",
        "download_file",
        "list_files",
        "list_my_files",
        "send_local_file",
        "delete_file",
        "search_and_send_file",
        "search_vault",
        "write_vault_note",
    }
)
FORBIDDEN_ON_QQ = frozenset(
    {
        "bash",
        "read",
        "write",
        "edit",
        "glob",
        "todo_write",
        "create_task",
        "update_task",
        "list_tasks",
        "get_task",
        "claim_task",
        "complete_task",
        "task",
        "load_skill",
        "connect_mcp",
    }
)


def _fn(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
            },
        },
    }


def _fmt_local(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def build_tools(ctx: ChatContext) -> tuple[list[dict], dict[str, Callable[..., str]]]:
    kb = get_knowledge_store()
    schedules = get_schedule_store()
    uid = ctx.user_id
    scope = ctx.recall_group_id
    storage_gid = ctx.storage_group_id
    channel = "group" if ctx.is_group else "private"

    schemas = [
        _fn("web_search", "上网搜索公开信息（关键词检索）。", {"query": {"type": "string"}}, ["query"]),
        _fn(
            "fetch_url",
            "打开用户给的网页/帖子链接，抽取正文与热评。"
            "用户贴了 URL 并说分析/总结/看看这个帖子时必须先调用本工具（或依赖系统已预取的正文）。"
            "支持 Reddit 短链与普通文章页。",
            {"url": {"type": "string", "description": "完整 http(s) 链接"}},
            ["url"],
        ),
        # —— 记忆（主名 + 兼容别名）——
        _fn(
            "save_memory",
            "写入当前用户长期记忆（情景层）。短偏好/原话用这个；"
            "长文招聘/路线/纪要用 synthesize_knowledge。",
            {
                "text": {"type": "string"},
                "title": {"type": "string", "description": "可选标题"},
                "kind": {
                    "type": "string",
                    "description": "note / doc / preference，默认 note",
                },
                "tags": {"type": "string", "description": "可选，逗号分隔"},
            },
            ["text"],
        ),
        _fn(
            "get_memory",
            "检索当前用户记忆（含知识卡片，语义优先）。",
            {
                "query": {"type": "string"},
                "kind": {"type": "string", "description": "可选过滤 kind"},
            },
            ["query"],
        ),
        _fn(
            "delete_memory",
            "按记忆 ID 删除当前用户条目。",
            {"memory_id": {"type": "string"}},
            ["memory_id"],
        ),
        _fn(
            "synthesize_knowledge",
            "增量语义归纳：提炼结构化事实，向量对齐后 Upsert/Merge 知识卡片。"
            "适用于招聘要求、学习路线、会议纪要等长文；重复主题会自动合并去重。",
            {"text": {"type": "string", "description": "待提炼的非结构化文本"}},
            ["text"],
        ),
        _fn(
            "list_knowledge_cards",
            "列出当前用户的知识卡片（主题/版本/摘要）。",
            {},
            [],
        ),
        # —— 催办 ——
        _fn(
            "schedule_reminder",
            "创建待办/会议/考试等任务，按类别自动生成多次本地催办（0 Token）。"
            "due_at 必须是 ISO8601（如 2026-10-20T10:00:00+08:00）。"
            "category: exam|meeting|activity|todo。"
            "考试=提前一周+隔两天+提前5小时/2小时+提前10分钟；"
            "会议/活动/待办=隔两天+提前1天/5小时/2小时+提前10分钟。",
            {
                "title": {"type": "string", "description": "事项标题"},
                "due_at": {"type": "string", "description": "到期/开始时间 ISO8601"},
                "category": {
                    "type": "string",
                    "description": "exam / meeting / activity / todo，默认 todo",
                },
                "notify_channel": {
                    "type": "string",
                    "description": "private 或 group；默认当前场景",
                },
            },
            ["title", "due_at"],
        ),
        _fn(
            "schedule_list",
            "列出当前用户任务列表（不含每次催办子点）。",
            {},
        ),
        _fn(
            "schedule_done",
            "将任务标为已完成（同时取消后续催办）。",
            {"schedule_id": {"type": "string"}},
            ["schedule_id"],
        ),
        _fn(
            "schedule_cancel",
            "取消任务及其全部催办。",
            {"schedule_id": {"type": "string"}},
            ["schedule_id"],
        ),
        # —— 文件 ——
        _fn(
            "download_file",
            "按 URL 下载到当前用户本地沙箱。",
            {
                "url": {"type": "string"},
                "filename": {"type": "string", "description": "可选文件名"},
            },
            ["url"],
        ),
        _fn("list_files", "列出当前作用域本地沙箱文件名。", {}),
        _fn(
            "list_my_files",
            "列文件：私聊=全部（按私聊/各群分组）；群聊=仅本群。"
            "用户说「有哪些文件/列出记住的文件」时用。",
            {},
        ),
        _fn(
            "send_local_file",
            "把已下载到本地的文件发回给当前用户（群或私聊）。"
            "群聊中也可发送私聊沙箱里的文件。",
            {
                "filename": {"type": "string"},
                "from_private": {
                    "type": "boolean",
                    "description": "true 时优先从私聊沙箱取文件",
                },
            },
            ["filename"],
        ),
        _fn(
            "delete_file",
            "按文件名或 id 准备删除用户文件：返回用途说明并要求用户回复「确认删除」。"
            "不要在用户未确认时真正删除。",
            {"filename": {"type": "string"}},
            ["filename"],
        ),
        _fn(
            "search_and_send_file",
            "按摘要/文件名/tags 模糊检索用户文件（含私聊上传 + 当前群），找到后发给当前用户。"
            "例如 query=张三的简历。群聊里可以调出私聊保存过的文件。",
            {"query": {"type": "string"}},
            ["query"],
        ),
        _fn(
            "search_vault",
            "在本地 Obsidian Vault 里语义检索笔记。"
            "用户说「在知识库搜… / vault 里有没有…」时用。",
            {"query": {"type": "string"}},
            ["query"],
        ),
        _fn(
            "write_vault_note",
            "AI 写一篇 Markdown 笔记写入本地 Vault（含 frontmatter），并尝试 Git commit。"
            "用户说「写一篇关于…的笔记并存入知识库」时用。",
            {
                "topic": {"type": "string", "description": "笔记主题"},
                "extra": {"type": "string", "description": "可选补充要求"},
            },
            ["topic"],
        ),
    ]

    def save_memory(
        text: str,
        title: str = "",
        kind: str = "note",
        tags: str = "",
    ) -> str:
        kb.kb_add(
            user_id=uid,
            group_id=storage_gid,
            text=text,
            source=channel,
            kind=kind or "note",
            title=title or "",
            metadata={"tags": [t.strip() for t in tags.split(",") if t.strip()]},
        )
        # 短回执：禁止把 id/全文塞给模型去复述刷屏
        return "OK"

    def get_memory(query: str, kind: str = "") -> str:
        hits = kb.kb_search(
            user_id=uid,
            query=query,
            group_id=scope,
            kind=kind or None,
        )
        if not hits:
            return "记忆里没有找到相关内容"
        lines = []
        for record, score in hits:
            where = f"群{record.group_id}" if record.group_id != "private" else "私聊"
            title = f"{record.title} | " if record.title else ""
            lines.append(
                f"- [{record.id}] ({record.kind}, {where}, {score:.3f}) "
                f"{title}{record.text}"
            )
        return "记忆召回：\n" + "\n".join(lines)

    def delete_memory(memory_id: str) -> str:
        ok = kb.kb_delete(user_id=uid, memory_id=memory_id)
        return "记忆已删除" if ok else "记忆不存在或无权删除"

    def synthesize_knowledge(text: str) -> str:
        from agent.knowledge.synthesis import upsert_knowledge

        result = upsert_knowledge(
            user_id=uid, text=text, group_id=storage_gid
        )
        return result.message

    def list_knowledge_cards_tool() -> str:
        from agent.knowledge.synthesis import list_knowledge_cards

        return list_knowledge_cards(user_id=uid)

    def schedule_reminder(
        title: str,
        due_at: str,
        category: str = "todo",
        notify_channel: str = "",
        remind_at: str = "",  # 兼容旧参数，忽略
    ) -> str:
        from agent.scheduler import get_reminder_scheduler

        ch = notify_channel.strip() or channel
        if ch not in ("private", "group"):
            ch = channel
        if ch == "group" and not ctx.is_group:
            ch = "private"
        parent, ticks = schedules.create_task_with_reminders(
            user_id=uid,
            group_id=storage_gid,
            title=title,
            due_at=due_at,
            category=category or "todo",
            channel=ch,
        )
        sched = get_reminder_scheduler()
        if sched:
            for t in ticks:
                sched.arm(t)
        cat = CATEGORY_LABELS.get(parent.category, parent.category)
        lines = [
            f"已加入任务列表 id={parent.id}",
            f"类型：{cat} | 事项：{parent.title}",
            f"到期：{_fmt_local(parent.due_at)}",
            f"已安排 {len(ticks)} 次催办（本地定时，不耗 Token）：",
        ]
        for t in ticks[:12]:
            local = datetime.fromisoformat(t.remind_at)
            if local.tzinfo is None:
                local = local.replace(tzinfo=timezone.utc)
            local_s = local.astimezone(timezone(timedelta(hours=8))).strftime(
                "%m-%d %H:%M"
            )
            lines.append(f"  · {t.label} @ {local_s}")
        if len(ticks) > 12:
            lines.append(f"  · …共 {len(ticks)} 次")
        lines.append("问「待办事项」或「我的日程」可看任务 list。")
        return "\n".join(lines)

    def schedule_list() -> str:
        items = schedules.list_for_user(
            user_id=uid,
            group_id=scope if ctx.is_group else None,
            tasks_only=True,
        )
        if not items:
            return "待办事项 list：（空）"
        lines = ["待办事项 list："]
        for i, s in enumerate(items, 1):
            cat = CATEGORY_LABELS.get(s.category, s.category)
            lines.append(
                f"{i}. [{s.id}] [{cat}] {s.title} | 到期 {_fmt_local(s.due_at)} | {s.status}"
            )
        return "\n".join(lines)

    def schedule_done(schedule_id: str) -> str:
        from agent.scheduler import get_reminder_scheduler

        kids = schedules.child_ids(schedule_id)
        ok = schedules.set_status(user_id=uid, schedule_id=schedule_id, status="done")
        if ok:
            sched = get_reminder_scheduler()
            if sched:
                sched.disarm(schedule_id)
                for kid in kids:
                    sched.disarm(kid)
        return "任务已完成，后续催办已停" if ok else "任务不存在"

    def schedule_cancel(schedule_id: str) -> str:
        from agent.scheduler import get_reminder_scheduler

        kids = schedules.child_ids(schedule_id)
        ok = schedules.set_status(
            user_id=uid, schedule_id=schedule_id, status="cancelled"
        )
        if ok:
            sched = get_reminder_scheduler()
            if sched:
                sched.disarm(schedule_id)
                for kid in kids:
                    sched.disarm(kid)
        return "任务已取消，催办已全部撤销" if ok else "任务不存在"

    def download(url: str, filename: str = "") -> str:
        path = download_url(
            url=url, user_id=uid, group_id=scope, filename=filename or None
        )
        return f"已下载到本地: {path}（需要时可用 send_local_file 发回）"

    def send_local(filename: str, from_private: bool = False) -> str:
        from agent.channel.client_ref import get_onebot_client
        from agent.user_files import user_dir

        client = get_onebot_client()
        if client is None:
            return "OneBot 未就绪，无法发文件"
        candidates = []
        if from_private or ctx.is_group:
            candidates.append(user_dir(uid, None) / filename)  # private
        candidates.append(user_dir(uid, scope) / filename)
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            # 索引里找本人文件
            from agent.files import get_file_index

            hits = get_file_index().find_by_name(uid, filename, limit=1)
            if hits and hits[0].local_path:
                from pathlib import Path

                p = Path(hits[0].local_path)
                if p.is_file():
                    return _upload_path(client, p)
            all_names = [n for _, n in list_all_files(uid)][:8]
            hint = "、".join(all_names) if all_names else "（空）"
            return f"找不到文件 {filename}。你有：{hint}"
        return _upload_path(client, path)

    def _upload_path(client, path) -> str:
        from agent.files.delivery import send_local_media

        return send_local_media(
            client,
            path=path,
            group_id=ctx.group_id if ctx.is_group else None,
            user_id=uid,
        )

    def list_my_files() -> str:
        from agent.files.delivery import list_user_files_human

        return list_user_files_human(
            uid,
            group_id=ctx.group_id,
            is_group=ctx.is_group,
            group_name=ctx.group_name or "",
        )

    def delete_file_tool(filename: str) -> str:
        """不直接删：登记待确认，说明用途。"""
        from agent.channel.pending import set_pending_delete
        from agent.files import get_file_index

        store = get_file_index()
        hits = store.find_by_name(uid, filename, limit=3)
        if not hits:
            # 沙箱直删仍要求确认：构造伪 pending
            names = list_files(uid, scope)
            if filename not in names:
                priv = list_files(uid, None)
                if filename not in priv:
                    return f"没找到文件「{filename}」。可先 list_my_files。"
            set_pending_delete(
                user_id=uid,
                file_id=f"sandbox:{filename}",
                file_name=filename,
                summary="沙箱本地文件（无索引摘要）",
                local_path="",
            )
            return (
                f"即将删除沙箱文件：{filename}\n"
                f"这个文件是干什么的：本地下载/保存的文件（无摘要）\n"
                f"确认删除请让用户回复「确认删除」，取消回「取消」。"
            )
        if len(hits) > 1:
            lines = [f"多个匹配「{filename}」，请用更精确的名字或 id："]
            for h in hits:
                lines.append(f"- [{h.id}] {h.file_name}：{h.summary or '无摘要'}")
            return "\n".join(lines)
        rec = hits[0]
        set_pending_delete(
            user_id=uid,
            file_id=rec.id,
            file_name=rec.file_name,
            summary=rec.summary or "",
            local_path=rec.local_path or "",
        )
        where = "私聊" if rec.group_id == "private" else f"群{rec.group_id}"
        return (
            f"即将删除：{rec.file_name} [{rec.id}]\n"
            f"来源：{where}\n"
            f"这个文件是干什么的：{rec.summary or '（无摘要）'}\n"
            f"请让用户回复「确认删除」或「取消」。"
        )

    def search_and_send_file(query: str) -> str:
        from agent.channel.client_ref import get_onebot_client
        from agent.files.delivery import search_send_or_recover

        client = get_onebot_client()
        if client is None:
            return "OneBot 未就绪，无法发文件"
        return search_send_or_recover(
            client=client,
            query=query,
            user_id=uid,
            group_id=storage_gid if ctx.is_group else None,
        )

    def search_vault_tool(query: str) -> str:
        from agent.vault.writer import search_vault

        return search_vault(query)

    def write_vault_note_tool(topic: str, extra: str = "") -> str:
        from agent.vault.writer import generate_and_write_note

        return generate_and_write_note(topic, extra=extra or "")

    def _wrap_search(text: str) -> str:
        from agent.channel.trust import wrap_untrusted

        return wrap_untrusted("web_search", text, max_len=3500)

    def _wrap_fetch(url: str) -> str:
        from agent.channel.trust import wrap_untrusted

        return wrap_untrusted("fetch_url", fetch_url(url), max_len=8000)

    handlers: dict[str, Callable[..., str]] = {
        "web_search": lambda query: _wrap_search(web_search(query)),
        "fetch_url": _wrap_fetch,
        "save_memory": save_memory,
        "get_memory": get_memory,
        "delete_memory": delete_memory,
        "synthesize_knowledge": synthesize_knowledge,
        "list_knowledge_cards": list_knowledge_cards_tool,
        "schedule_reminder": schedule_reminder,
        "schedule_list": schedule_list,
        "schedule_done": schedule_done,
        "schedule_cancel": schedule_cancel,
        "download_file": download,
        "list_files": lambda: (
            "文件列表：\n" + ("\n".join(list_files(uid, scope)) or "(空)")
        ),
        "list_my_files": list_my_files,
        "send_local_file": send_local,
        "delete_file": delete_file_tool,
        "search_and_send_file": search_and_send_file,
        "search_vault": search_vault_tool,
        "write_vault_note": write_vault_note_tool,
    }

    names = {s["function"]["name"] for s in schemas}
    assert names == set(handlers), "QQ 工具 schema/handler 不一致"
    assert names <= QQ_TOOL_NAMES
    assert not (names & FORBIDDEN_ON_QQ), f"QQ 路径混入 coding 工具: {names & FORBIDDEN_ON_QQ}"
    return schemas, handlers
