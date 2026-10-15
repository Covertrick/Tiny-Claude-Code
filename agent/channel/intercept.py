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

# 保存上面的文件（群聊 @）——含「记住这个文件/表情包」；避免误伤纯偏好「记住我喜欢米饭」
_SAVE_ABOVE_RE = re.compile(
    r"(帮我)?(把)?(上面|刚才|上方|前面|上一条|最近).{0,6}(的)?(那个)?(文件|附件|图|图片|表情包)?"
    r".{0,6}(保存|存一下|存下|收下|收藏|入库|记住)|"
    r"(帮我)?(保存|存一下|存下|收下|记住).{0,8}(上面|刚才|上方|前面|上一条|这个|那个)"
    r".{0,6}(文件|附件|图|图片|表情包)?|"
    r"(帮我)?(记住|保存).{0,4}(这个|那个)?(文件|附件|图|图片|表情包)|"
    r"(这是|这个是).{0,40}(文件|附件|图|图片|表情包).{0,8}(记住|保存)|"
    r"帮我保存(上面|刚才)?(的)?(文件|附件)",
    re.I,
)

# 文件列表（私聊当场回；群聊再走私聊）
_FILE_LIST_RE = re.compile(
    r"^(你)?(现在)?(有哪些|有什么|看看|查看|列出|给我看)?(我的|我拥有的|我上传的)?"
    r"(文件|附件)(列表|list)?[？?！!\s～~]*$"
    r"|^(文件列表|我的文件|有哪些文件|现在有哪些文件|我有哪些文件)[？?！!\s～~]*$"
    r"|^(把)?(我)?(让你)?(记住的|保存的|存的)?(所有|全部)?(文件|附件|表情包)"
    r".{0,12}(列出来|列一下|列表|发给我|给我)[？?！!\s～~]*$"
    r"|^(列出|列举|罗列).{0,16}(文件|附件|表情包)[？?！!\s～~]*$",
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

    # —— 增量知识卡片 ——
    synth = _try_synthesis_intercept(ctx, text)
    if synth is not None:
        return synth

    # —— 闪念 / 记账 / 消费统计（Phase 2，0~极少 Token）——
    life = _try_life_intercept(ctx, text)
    if life is not None:
        return life

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

    # —— 保存上面的文件 / 记住表情包 ——
    if ctx.is_group and ctx.group_id and _SAVE_ABOVE_RE.search(text):
        return _save_above_files(ctx)

    # —— 群内喊出发图/文件（含事后回捞，不驱私聊）——
    send = _try_send_media_intercept(ctx, text)
    if send is not None:
        return send

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


_SYNTH_RE = re.compile(
    r"^(归纳一下|提炼知识|知识入库|合并知识|总结入库)[:：\s]*(?P<body>.+)$",
    re.I | re.S,
)
_CARDS_LIST_RE = re.compile(
    r"^(我的)?(知识卡片|知识库)(列表)?[？?！!\s～~]*$"
    r"|^(有哪些知识卡片|看看知识卡片)[？?！!\s～~]*$",
    re.I,
)


def _try_synthesis_intercept(ctx: ChatContext, text: str) -> str | None:
    if _CARDS_LIST_RE.match(text):
        from agent.knowledge.synthesis import list_knowledge_cards

        return list_knowledge_cards(user_id=ctx.user_id)
    m = _SYNTH_RE.match(text)
    if m:
        body = (m.group("body") or "").strip()
        if not body:
            return "后面跟要归纳的内容，例如「归纳一下 招聘Java要会Spring」。"
        from agent.knowledge.synthesis import upsert_knowledge

        result = upsert_knowledge(
            user_id=ctx.user_id,
            text=body,
            group_id=ctx.storage_group_id,
        )
        return result.message
    return None


_CAPTURE_RE = re.compile(
    r"^(记一下|闪念|记下|备忘)[:：\s]*(?P<body>.+)$", re.I
)
_NOTES_LIST_RE = re.compile(
    r"^(我的)?(闪念|备忘)(列表|记录)?[？?！!\s～~]*$"
    r"|^(有哪些闪念|看看闪念)[？?！!\s～~]*$",
    re.I,
)
_NOTES_SEARCH_RE = re.compile(
    r"^(找闪念|搜索闪念|查闪念)[:：\s]*(?P<q>.+)$", re.I
)
_EXPENSE_ASK_RE = re.compile(
    r"(本周|这周|这个月|本月|今天|今日)?.*(花了多少|消费统计|支出统计|花销|账单)",
    re.I,
)
_EXPENSE_LIST_RE = re.compile(r"^(最近账单|账单列表)[？?！!\s～~]*$", re.I)
_DIGEST_RE = re.compile(r"^(今日速递|资讯速递|早报资讯)[？?！!\s～~]*$", re.I)
_ADMIN_RE = re.compile(
    r"^/(metrics|status|plugins|reload)(?:\s+(?P<arg>\S+))?\s*$", re.I
)
_DASHBOARD_RE = re.compile(
    r"^(打开|开启)?(控制台|仪表盘|dashboard|管理面板|web面板)[？?！!\s～~]*$",
    re.I,
)
_VAULT_NOTE_RE = re.compile(
    r"^(帮我)?(写|生成)(一篇|一条|个)?(关于|有关)?\s*(?P<topic>.+?)\s*"
    r"(的)?(笔记|文档|文章)(并)?(存入|写入|保存到)?(知识库|vault|obsidian)?[？?！!\s～~]*$",
    re.I,
)
_VAULT_SEARCH_RE = re.compile(
    r"^(在)?(知识库|vault|obsidian|笔记库)(里|中)?(搜|搜索|找|查)\s*(?P<q>.+)$"
    r"|^(搜|搜索|找)(知识库|vault|笔记)\s*(?P<q2>.+)$",
    re.I,
)
_VAULT_REINDEX_RE = re.compile(
    r"^(重建|全量|重新)?(索引|扫描)(知识库|vault|obsidian|笔记库)?[？?！!\s～~]*$",
    re.I,
)
_CALENDAR_EXPORT_RE = re.compile(
    r"^(导出日历|导出日程|导出ics|导出ICS|同步到日历)[？?！!\s～~]*$",
    re.I,
)
_USAGE_RE = re.compile(
    r"^(用量|我的用量|token统计|Token统计|/usage)[？?！!\s～~]*$",
    re.I,
)


def _try_vault_intercept(ctx: ChatContext, text: str) -> str | None:
    """知识库写笔记 / 检索 / 重建索引。"""
    if _VAULT_REINDEX_RE.match(text):
        from agent.vault.sync import reindex_vault

        return reindex_vault()

    m_note = _VAULT_NOTE_RE.match(text)
    if m_note:
        topic = (m_note.group("topic") or "").strip()
        # 去掉可能粘上的「并存入知识库」尾巴
        topic = re.sub(
            r"(并)?(存入|写入|保存到)?(知识库|vault|obsidian)?$",
            "",
            topic,
            flags=re.I,
        ).strip()
        from agent.vault.writer import generate_and_write_note

        return generate_and_write_note(topic)

    m_s = _VAULT_SEARCH_RE.match(text)
    if m_s:
        q = (m_s.group("q") or m_s.group("q2") or "").strip()
        from agent.vault.writer import search_vault

        return search_vault(q)
    return None


def _try_life_intercept(ctx: ChatContext, text: str) -> str | None:
    admin = _try_admin_intercept(ctx, text)
    if admin is not None:
        return admin

    m = _CAPTURE_RE.match(text)
    if m:
        from agent.life.capture import quick_capture

        return quick_capture(
            user_id=ctx.user_id,
            text=m.group("body").strip(),
            group_id=ctx.storage_group_id,
        )
    if _NOTES_LIST_RE.match(text):
        from agent.life.capture import list_notes

        return list_notes(user_id=ctx.user_id)
    m_ns = _NOTES_SEARCH_RE.match(text)
    if m_ns:
        from agent.life.capture import search_notes

        return search_notes(user_id=ctx.user_id, query=m_ns.group("q").strip())
    if _EXPENSE_LIST_RE.match(text):
        from agent.life.expense import list_recent

        return list_recent(user_id=ctx.user_id)
    if _EXPENSE_ASK_RE.search(text):
        from agent.life.expense import summarize_expenses

        return summarize_expenses(user_id=ctx.user_id, text=text)
    if re.search(
        r"(花了|消费|支出|付了).{0,12}\d|(?:\d+(?:\.\d{1,2})?\s*(元|块|块钱|￥|¥))",
        text,
    ):
        from agent.life.expense import add_expense

        exp = add_expense(user_id=ctx.user_id, text=text)
        if exp:
            return f"已记账：{exp.note} {exp.amount:.2f} 元（{exp.category}）"
    if _DIGEST_RE.match(text):
        from agent.life.monitor import fetch_digest

        return fetch_digest(use_llm=False)
    return None


def _try_admin_intercept(ctx: ChatContext, text: str) -> str | None:
    from agent.config import ADMIN_PORT, OWNER_QQ

    if _CALENDAR_EXPORT_RE.match(text):
        from agent.calendar_sync import schedules_to_ics

        path = schedules_to_ics(user_id=ctx.user_id)
        return f"已导出 ICS：{path}\n可导入 Google/Outlook 日历。双向云同步见路线图。"

    if _USAGE_RE.match(text):
        from agent.observability.usage import get_usage_store

        s = get_usage_store().summary(user_id=ctx.user_id)
        return (
            f"你的用量：调用 {s['calls']} 次，"
            f"合计约 {s['total_tokens']} tokens"
            f"（prompt {s['prompt_tokens']} / completion {s['completion_tokens']}）"
        )

    if _DASHBOARD_RE.match(text):
        if ADMIN_PORT <= 0:
            return "请设置 QQ_ADMIN_PORT=8787 并安装 fastapi uvicorn 后重启。"
        if ctx.is_group:
            return "安全起见，请私聊我发「打开控制台」，链接只发给你自己。"
        try:
            from agent.admin.auth import build_magic_link, public_base_url
            from agent.admin.tunnel import wait_public_base_url
            from agent.config import ADMIN_AUTO_OPEN, ADMIN_MAGIC_TTL, ADMIN_TUNNEL

            if ADMIN_TUNNEL not in ("off", "0", "false", "no", "none"):
                wait_public_base_url(timeout=25.0)
            url = build_magic_link(user_qq=str(ctx.user_id), port=ADMIN_PORT)
            mins = max(1, ADMIN_MAGIC_TTL // 60)
            base = public_base_url(port=ADMIN_PORT)
            opened = ""
            if ADMIN_AUTO_OPEN:
                try:
                    import webbrowser

                    webbrowser.open(url)
                    opened = "\n已在跑机器人的电脑上尝试打开浏览器。"
                except Exception:
                    opened = ""
            if base.startswith("https://"):
                tip = "公网 HTTPS，手机流量也能开（限时有效）。"
            else:
                tip = (
                    "公网隧道还没好或失败，当前仅局域网/本机。"
                    "可等半分钟再发「打开控制台」，或检查 cloudflared 下载。"
                )
            return (
                f"你的控制台（约 {mins} 分钟有效，只看你自己的数据）：\n"
                f"{url}\n"
                f"{tip}"
                f"{opened}\n"
                f"别把链接转给别人。"
            )
        except Exception as e:
            return f"签发失败：{e}"

    vault = _try_vault_intercept(ctx, text)
    if vault is not None:
        return vault

    m = _ADMIN_RE.match(text)
    if not m:
        return None
    if OWNER_QQ and str(ctx.user_id) != str(OWNER_QQ):
        return "这是主人专用指令哦。"
    cmd = m.group(1).lower()
    arg = (m.group("arg") or "").strip()
    if cmd in ("metrics", "status"):
        from agent.admin.metrics import snapshot_metrics

        snap = snapshot_metrics()
        mem = snap["memory"]
        send = snap["send"]
        return (
            f"状态 pid={snap['pid']} embed={snap['embedding']}\n"
            f"记忆 total={mem['total']} semantic={mem['semantic']} "
            f"archived={mem['archived']}\n"
            f"发送 熔断剩余={send['breaker_open_remaining']:.0f}s "
            f"令牌≈{send['bucket_tokens']}"
        )
    if cmd == "plugins":
        try:
            from plugins.loader import get_registry

            regs = get_registry().plugins
            if not regs:
                return "插件：（空）"
            lines = ["已加载插件："]
            for name, info in regs.items():
                lines.append(f"- {name} v{info.version} {info.description}")
            return "\n".join(lines)
        except Exception as e:
            return f"插件列表失败：{e}"
    if cmd == "reload":
        name = arg or "echo"
        try:
            from plugins.loader import reload_plugin

            ok = reload_plugin(name)
            return f"重载插件 {name}：" + ("成功" if ok else "失败")
        except Exception as e:
            return f"重载失败：{e}"
    return None


_SEND_MEDIA_RE = re.compile(
    r"(把|发|甩|来一张|给我|再发).{0,36}(出来|发我|一下|过来)?|"
    r".{0,24}(表情包|gif|那张图|那个图|那个文件).{0,10}(发|来|甩)|"
    r"^(发|甩).{1,40}$",
    re.I,
)
# 短标题召回：像「大肥鱼殴打GPT」这种非问句
_SHORT_ALIAS_RE = re.compile(
    r"^[\w\u4e00-\u9fff·\-（）()\s]{2,40}$",
)


def _try_send_media_intercept(ctx: ChatContext, text: str) -> str | None:
    from agent.channel.client_ref import get_onebot_client
    from agent.files.delivery import clean_caption, search_send_or_recover

    # 「列文件」绝不能误进发送/回捞
    if re.search(r"(列出|列举|列表|有哪些|全部.*文件|所有文件|罗列)", text):
        return None

    want_send = bool(_SEND_MEDIA_RE.search(text))
    alias = clean_caption(text)
    short_ok = bool(
        alias
        and 2 <= len(alias) <= 40
        and _SHORT_ALIAS_RE.match(alias)
        and not re.search(r"(吗|呢|怎么|为什么|多少|几点|什么|谁|哪|是否)", text)
    )
    if not want_send and not short_ok:
        return None
    # 短别名召回：必须索引或近期缓存已有线索，避免误拦普通闲聊
    if not want_send and short_ok:
        store = get_file_index()
        hits = store.search_for_user(
            alias,
            user_id=ctx.user_id,
            group_id=ctx.group_id if ctx.is_group else None,
            limit=1,
        )
        recent = []
        if ctx.is_group and ctx.group_id:
            recent = RECENT_FILES.recent(
                ctx.group_id, limit=3, within_seconds=600, uploader_id=ctx.user_id
            )
        if not hits and not recent:
            return None
    client = get_onebot_client()
    if client is None:
        return "OneBot 还没连上，稍后再喊我发。"
    query = alias or text
    query = re.sub(
        r"(把|发|甩|来一张|给我|再发|出来|发我|一下|过来)",
        " ",
        query,
    )
    query = re.sub(r"\s+", " ", query).strip() or alias or text
    return search_send_or_recover(
        client=client,
        query=query,
        user_id=ctx.user_id,
        group_id=ctx.group_id if ctx.is_group else None,
    )


def _save_above_files(ctx: ChatContext) -> str:
    from agent.files.pipeline import clean_caption

    gid = ctx.group_id or ""
    caption = clean_caption(ctx.text or "")
    recent = RECENT_FILES.recent(
        gid, limit=5, within_seconds=1800, uploader_id=None
    )
    mine = [x for x in recent if x.uploader_id == ctx.user_id]
    picks = mine[:2] if mine else recent[:1]
    if not picks:
        return (
            "我没看到上面有可保存的图/文件。"
            "直接在本群再发一次（可配上名字），不用去私聊。"
        )

    store = get_file_index()
    records = []
    for item in picks:
        # 已有同文件且已落盘：只补别名
        existing = [
            r
            for r in store.list_for_user(ctx.user_id, limit=40)
            if r.group_id == gid and r.file_name == item.name
        ]
        if not existing:
            existing = [
                r
                for r in store.search(item.name, group_id=gid, limit=5)
                if r.file_name == item.name
            ]
        if (
            existing
            and existing[0].local_path
            and caption
            and caption not in (existing[0].summary or "")
        ):
            store.update_summary(
                existing[0].id,
                caption,
                tags=((existing[0].tags or "") + f",{caption}").strip(","),
            )
            rec = store.get(existing[0].id)
            if rec:
                records.append(rec)
            continue
        if existing and existing[0].local_path and Path(existing[0].local_path).is_file():
            records.append(existing[0])
            continue
        # 重新下载落库 + 绑别名
        seg = RECENT_FILES.to_segment(item)
        records.extend(
            ingest_file_segments(
                segments=[seg],
                group_id=gid,
                uploader_id=item.uploader_id or ctx.user_id,
                summarize=False,
                caption=caption or item.caption or "",
            )
        )
    ack = format_ingest_reply(records)
    return ack or "没存上。再发一次到本群即可，不用私聊。"


def _send_file_list_private(ctx: ChatContext) -> str:
    from agent.files.delivery import list_user_files_human

    # 群聊：只列本群；私聊：列私聊+所有群（分组）
    return list_user_files_human(
        ctx.user_id,
        group_id=ctx.group_id,
        is_group=ctx.is_group,
        group_name=ctx.group_name or "",
    )


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
