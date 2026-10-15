"""消息路由：语音转写缓存 / 文件索引 / @ 才进 Agent。

并发信号量 + 用户冷却；发送走 safe_send（重试/分片/引用）。
"""

from __future__ import annotations

import threading
import time

from agent.channel.context import ChatContext
from agent.channel.file_cache import RECENT_FILES
from agent.channel.group_cache import GROUP_CACHE
from agent.channel.intercept import try_intercept
from agent.channel.lifecycle import handle_event as handle_lifecycle_event
from agent.channel.message import (
    extract_cache_text,
    extract_file_segments,
    extract_text,
    is_at_bot,
    strip_at,
)
from agent.channel.onebot import OneBotClient
from agent.channel.proactive import KeywordWatcher
from agent.channel.run import run_qq_agent
from agent.channel.send import safe_send_msg
from agent.channel.session import SESSIONS, session_key
from agent.config import (
    AGENT_CONCURRENCY,
    BOT_QQ,
    GROUP_AT_DEBOUNCE_SECONDS,
    USER_COOLDOWN_SECONDS,
)
from agent.files.pipeline import format_ingest_reply, ingest_file_segments


class MessageRouter:
    def __init__(self, client: OneBotClient):
        self.client = client
        self.bot_qq = str(BOT_QQ or "")
        self._busy: set[str] = set()
        self._lock = threading.Lock()
        self._group_at_ts: dict[str, float] = {}
        self._user_cooldown: dict[str, float] = {}
        self._sem = threading.Semaphore(max(1, AGENT_CONCURRENCY))
        self.keywords = KeywordWatcher(client)

    def handle_event(self, event: dict) -> None:
        # 异地登录 / 被踢 → 退出全部进程
        if handle_lifecycle_event(event):
            return

        if event.get("post_type") != "message":
            return
        msg_type = event.get("message_type")
        if msg_type not in ("group", "private"):
            return

        raw = event.get("message")
        self_id = str(event.get("self_id") or self.bot_qq or self.client.self_id or "")
        if self_id:
            self.bot_qq = self_id

        is_group = msg_type == "group"
        user_id = str(event.get("user_id") or "")
        group_id = str(event.get("group_id") or "") if is_group else None
        sender = event.get("sender") or {}
        nickname = sender.get("card") or sender.get("nickname") or ""
        message_id = event.get("message_id")
        at_bot = is_at_bot(raw, self.bot_qq) if is_group else True
        cache_text = extract_cache_text(raw)
        files = extract_file_segments(raw)

        # 群聊附件进近期缓存（供「保存上面的文件」）
        if is_group and group_id and files:
            RECENT_FILES.append(
                group_id,
                uploader_id=user_id,
                user=nickname or user_id,
                segments=files,
            )
            if cache_text:
                GROUP_CACHE.append(
                    group_id,
                    user=nickname or user_id,
                    text=f"{cache_text} [附件:{files[0].get('name') or 'file'}]",
                )
            else:
                names = "、".join(f.get("name") or "file" for f in files[:3])
                GROUP_CACHE.append(
                    group_id,
                    user=nickname or user_id,
                    text=f"[附件:{names}]",
                )

        # —— 群聊未 @：缓存 + 静默存文件 + 关键词（全 0 Token）——
        if is_group and not at_bot:
            if cache_text and not files:
                GROUP_CACHE.append(
                    group_id or "", user=nickname or user_id, text=cache_text
                )
                self.keywords.on_group_text(
                    group_id=group_id or "",
                    user=nickname or user_id,
                    text=cache_text,
                )
            elif cache_text:
                self.keywords.on_group_text(
                    group_id=group_id or "",
                    user=nickname or user_id,
                    text=cache_text,
                )
            if files and group_id:
                threading.Thread(
                    target=self._silent_ingest,
                    kwargs={
                        "files": files,
                        "group_id": group_id,
                        "uploader_id": user_id,
                    },
                    daemon=True,
                ).start()
            return

        # @ / 私聊
        if is_group and group_id and cache_text and not files:
            GROUP_CACHE.append(group_id, user=nickname or user_id, text=cache_text)

        text = strip_at(extract_text(raw), self.bot_qq)

        # 用户冷却
        cool_key = f"{msg_type}:{group_id or 'p'}:{user_id}"
        now = time.time()
        last_cool = self._user_cooldown.get(cool_key, 0)
        if now - last_cool < USER_COOLDOWN_SECONDS:
            self._reply(
                event,
                "你慢点，我喘不过气了",
                reply_to=message_id,
                chunk=False,
            )
            return
        self._user_cooldown[cool_key] = now

        if is_group and group_id:
            last = self._group_at_ts.get(group_id, 0)
            if now - last < GROUP_AT_DEBOUNCE_SECONDS:
                print(f"[qq] debounce drop group={group_id}")
                return
            self._group_at_ts[group_id] = now

        busy_key = cool_key
        with self._lock:
            if busy_key in self._busy:
                self._reply(
                    event,
                    "上一条还在处理，稍等一下～",
                    reply_to=message_id,
                    chunk=False,
                )
                return
            self._busy.add(busy_key)

        group_context = (
            GROUP_CACHE.snapshot(group_id, limit=10) if is_group and group_id else ""
        )

        def _job() -> None:
            acquired = False
            try:
                # 文件 + @ → 摘要入库（唯一文件路径烧 Token 点）
                if files and (group_id or not is_group):
                    gid = group_id or "private"
                    records = ingest_file_segments(
                        segments=files,
                        group_id=gid,
                        uploader_id=user_id,
                        summarize=True,
                        group_context=group_context,
                    )
                    ack = format_ingest_reply(records)
                    if ack and not text:
                        self._reply(event, ack, reply_to=message_id)
                        return
                    if ack and text:
                        # 先回执文件，再处理文字意图
                        self._reply(event, ack, reply_to=message_id, chunk=False)

                if not text and not files:
                    self._reply(
                        event,
                        "在的，直接说要我记待办、搜文件还是下东西～",
                        reply_to=message_id,
                        chunk=False,
                    )
                    return
                if not text:
                    return

                if not self._sem.acquire(timeout=45):
                    self._reply(
                        event,
                        "现在有点忙，请稍后再试～",
                        reply_to=message_id,
                        chunk=False,
                    )
                    return
                acquired = True
                ctx = ChatContext(
                    user_id=user_id,
                    group_id=group_id,
                    is_group=is_group,
                    nickname=nickname,
                    text=text,
                    group_context=group_context,
                )
                self._reply(
                    event,
                    self._process(ctx),
                    reply_to=message_id,
                    chunk=True,
                )
            except Exception as e:
                self._reply(
                    event, f"出错了：{e}", reply_to=message_id, chunk=False
                )
            finally:
                if acquired:
                    self._sem.release()
                with self._lock:
                    self._busy.discard(busy_key)

        threading.Thread(target=_job, daemon=True).start()

    def _silent_ingest(
        self, *, files: list, group_id: str, uploader_id: str
    ) -> None:
        try:
            records = ingest_file_segments(
                segments=files,
                group_id=group_id,
                uploader_id=uploader_id,
                summarize=False,
            )
            print(
                f"[files] 静默登记 {len(records)} 个文件 group={group_id} "
                f"（无摘要 0 Token）"
            )
        except Exception as e:
            print(f"[files] 静默入库失败: {e}")

    def _process(self, ctx: ChatContext) -> str:
        skey = session_key(
            user_id=ctx.user_id, group_id=ctx.group_id, is_group=ctx.is_group
        )
        intercepted = try_intercept(ctx)
        if intercepted is not None:
            print(f"[qq] → intercept user={ctx.user_id} text={ctx.text[:40]}")
            SESSIONS.append(skey, "user", ctx.text)
            SESSIONS.append(skey, "assistant", intercepted)
            return intercepted

        history = SESSIONS.load(skey)
        print(
            f"[qq] → agent_loop user={ctx.user_id} group={ctx.group_id} "
            f"text={ctx.text[:80]} "
            f"ctx_lines={ctx.group_context.count(chr(10))+1 if ctx.group_context else 0}"
        )
        reply = run_qq_agent(ctx=ctx, history=history)
        SESSIONS.append(skey, "user", ctx.text)
        SESSIONS.append(skey, "assistant", reply)
        print(f"[qq] ← reply len={len(reply)}")
        return reply

    def _reply(
        self,
        event: dict,
        text: str,
        *,
        reply_to: int | str | None = None,
        chunk: bool = True,
    ) -> None:
        text = (text or "").strip()
        if not text:
            return
        if len(text) > 1500:
            text = text[:1500] + "…"
        group_id = (
            event.get("group_id")
            if event.get("message_type") == "group"
            else None
        )
        user_id = event.get("user_id") if group_id is None else None
        safe_send_msg(
            self.client,
            group_id=group_id,
            user_id=user_id,
            message=text,
            reply_to=reply_to,
            chunk=chunk,
        )
