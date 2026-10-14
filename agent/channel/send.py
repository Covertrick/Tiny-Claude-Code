"""可靠发送：重试 + 降级 + 分片 + 引用回复（同步版，不引入全量 asyncio）。"""

from __future__ import annotations

import re
import time
from typing import Any

from agent.config import REPLY_CHUNK_DELAY, SEND_RETRY, SEND_RETRY_DELAY


def _chunks(text: str, max_parts: int = 3) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= 80:
        return [text]
    # 先按换行，再按句号/问号
    parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    if len(parts) == 1:
        parts = [
            p.strip()
            for p in re.split(r"(?<=[。！？.!？])\s*", text)
            if p.strip()
        ]
    if len(parts) <= 1:
        return [text]
    if len(parts) <= max_parts:
        return parts
    # 合并成 max_parts 段
    size = (len(parts) + max_parts - 1) // max_parts
    merged = []
    for i in range(0, len(parts), size):
        merged.append("\n".join(parts[i : i + size]))
    return merged[:max_parts]


def _with_reply(message: str | list, reply_message_id: int | str | None) -> str | list:
    if not reply_message_id:
        return message
    reply_seg = {"type": "reply", "data": {"id": str(reply_message_id)}}
    if isinstance(message, list):
        return [reply_seg, *message]
    return [reply_seg, {"type": "text", "data": {"text": str(message)}}]


def safe_send_msg(
    client: Any,
    *,
    group_id: int | str | None = None,
    user_id: int | str | None = None,
    message: str | list,
    reply_to: int | str | None = None,
    chunk: bool = True,
    max_retries: int | None = None,
    retry_delay: float | None = None,
) -> bool:
    """发送消息：最多重试；失败则降级为纯文本。返回是否至少成功一次。"""
    retries = max_retries if max_retries is not None else SEND_RETRY
    delay = retry_delay if retry_delay is not None else SEND_RETRY_DELAY

    payloads: list[str | list]
    if chunk and isinstance(message, str):
        payloads = _chunks(message)
    else:
        payloads = [message]

    all_ok = True
    for i, part in enumerate(payloads):
        body = _with_reply(part, reply_to if i == 0 else None)
        ok = _send_once(
            client,
            group_id=group_id,
            user_id=user_id,
            message=body,
            retries=retries,
            delay=delay,
        )
        if not ok:
            # 降级：纯文本
            plain = part if isinstance(part, str) else _seg_to_text(part)
            if plain and plain != part:
                ok = _send_once(
                    client,
                    group_id=group_id,
                    user_id=user_id,
                    message=plain[:1500],
                    retries=retries,
                    delay=delay,
                )
        all_ok = all_ok and ok
        if i < len(payloads) - 1 and ok:
            time.sleep(REPLY_CHUNK_DELAY)
    return all_ok


def _seg_to_text(message: list) -> str:
    parts = []
    for seg in message:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") == "text":
            parts.append(str((seg.get("data") or {}).get("text") or ""))
        elif seg.get("type") == "at":
            parts.append(f"@{(seg.get('data') or {}).get('qq') or ''}")
    return "".join(parts).strip()


def _send_once(
    client: Any,
    *,
    group_id: int | str | None,
    user_id: int | str | None,
    message: str | list,
    retries: int,
    delay: float,
) -> bool:
    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            if group_id is not None:
                client.send_group_msg(group_id, message)
            elif user_id is not None:
                client.send_private_msg(user_id, message)
            else:
                raise ValueError("group_id 与 user_id 都为空")
            return True
        except Exception as e:
            last_err = e
            print(f"[send] 失败 attempt={attempt+1}/{retries}: {e}")
            if attempt + 1 < retries:
                time.sleep(delay)
    if last_err:
        print(f"[send] 最终失败: {last_err}")
    return False
