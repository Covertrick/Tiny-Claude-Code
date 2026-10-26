"""可靠发送：令牌桶 + 抖动 + 风控熔断 + 重试/降级/分片/引用。"""

from __future__ import annotations

import re
import time
from typing import Any

from agent.channel.rate_limit import (
    get_send_breaker,
    get_send_bucket,
    is_risk_error,
    jitter_sleep,
)
from agent.config import REPLY_CHUNK_DELAY, SEND_RETRY, SEND_RETRY_DELAY


def strip_markdown(text: str) -> str:
    """把模型偶发的 Markdown 收成 QQ 可读纯文本。"""
    if not text:
        return ""
    s = text
    s = re.sub(r"```[\w]*\n?", "", s)
    s = s.replace("```", "")
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"(?m)^#{1,6}\s*", "", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", s)
    s = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", s)
    s = re.sub(r"(?m)^\s*[-*+]\s+", "", s)
    s = re.sub(r"(?m)^>\s?", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def sanitize_user_reply(text: str) -> str:
    """发送前清洗：禁止把哈希/UUID/后台摘要等技术字段甩给用户。"""
    if not text:
        return ""
    s = strip_markdown(text)
    s = re.sub(r"</?untrusted_content[^>]*>", "", s, flags=re.I)
    # 只有短确认才折叠，避免把正常回答（含「摘要」「之前」）整段换掉
    if len(s) <= 40 and re.search(
        r"(已更新记忆|两条关联|之前那版|以你这次说的为准)", s
    ):
        return "记好啦 [OK]"
    # 工具/后台复述 → 拟人短句（必须同时像文件回执，不能只凭「摘要：」）
    if re.search(
        r"(已为你保存|已保存|已登记|已落库|命中\s*\[|已发出图片|已发送文件).{0,120}"
        r"(摘要|file_id|hash|content_hash|\.gif|\.png|\.jpg|表情)",
        s,
        re.I,
    ) or re.search(r"命中\s*\[", s):
        if re.search(r"(gif|png|jpg|jpeg|webp|表情|图|命中|发出)", s, re.I):
            if re.search(r"(发出|命中|发好)", s):
                return "来~"
            return "收下啦！[大笑]"
        return "收到，已归档～"
    # 长十六进制 / UUID
    s = re.sub(r"\b[0-9a-fA-F]{16,}\b", "", s)
    s = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "",
        s,
    )
    # 技术字段行
    s = re.sub(
        r"(?im)^.*\b(file_id|content_hash|sha256|local_path|blob_path|"
        r"retcode|status\s*=)\b.*$",
        "",
        s,
    )
    s = re.sub(r"(?i)\b(file_id|content_hash|sha256)\s*[=:：]\s*\S+", "", s)
    s = re.sub(r"命中\s*\[[^\]]+\]\s*", "", s)
    s = re.sub(r"（群\d+）|（私聊）", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip(" ，,;；\n")
    # 清洗后只剩残渣 → 兜底口语
    if not s or re.fullmatch(r"[\W_\d]+", s):
        return "嗯嗯～"
    if len(s) > 20 and s.count("摘要") + s.count("hash") + s.count("file_id") >= 1:
        return "记下了～"
    return s


def _chunks(text: str, max_parts: int = 2) -> list[str]:
    """仅对很长回复分片，避免把一句确认拆成三条刷屏。"""
    text = strip_markdown(text or "")
    if not text:
        return []
    # 短确认 / 中等回复一律整条发
    if len(text) <= 160:
        return [text]
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
    """发送消息：令牌桶限流 + 抖动间隔 + 风控熔断 + 重试降级。"""
    breaker = get_send_breaker()
    if not breaker.allow():
        left = breaker.remaining()
        print(f"[send] 熔断中，跳过发送（剩余 {left:.0f}s）")
        # 熔断时仍尝试一次极简纯文本（降级），失败则放弃
        plain = message if isinstance(message, str) else _seg_to_text(message)
        if not plain:
            return False
        try:
            get_send_bucket().acquire(timeout=5)
            if group_id is not None:
                client.send_group_msg(group_id, plain[:200] + "…（限流降级）")
            elif user_id is not None:
                client.send_private_msg(user_id, plain[:200] + "…（限流降级）")
            else:
                return False
            return True
        except Exception as e:
            print(f"[send] 熔断降级失败: {e}")
            return False

    retries = max_retries if max_retries is not None else SEND_RETRY
    delay = retry_delay if retry_delay is not None else SEND_RETRY_DELAY

    payloads: list[str | list]
    if isinstance(message, str):
        message = sanitize_user_reply(message)
        if not message:
            return True
    elif isinstance(message, list):
        # 清洗文本段，保留 reply/image/file 等
        cleaned: list = []
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "text":
                data = dict(seg.get("data") or {})
                t = sanitize_user_reply(str(data.get("text") or ""))
                if not t:
                    continue
                data["text"] = t
                cleaned.append({"type": "text", "data": data})
            else:
                cleaned.append(seg)
        message = cleaned or message
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
            jitter_sleep(REPLY_CHUNK_DELAY)
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
    bucket = get_send_bucket()
    breaker = get_send_breaker()
    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        if not breaker.allow():
            print(f"[send] 熔断中，中止重试")
            return False
        if not bucket.acquire(timeout=20):
            print("[send] 令牌桶等待超时")
            return False
        try:
            if group_id is not None:
                client.send_group_msg(group_id, message)
            elif user_id is not None:
                client.send_private_msg(user_id, message)
            else:
                raise ValueError("group_id 与 user_id 都为空")
            breaker.on_success()
            return True
        except Exception as e:
            last_err = e
            risk = is_risk_error(e)
            breaker.on_failure(risk=risk)
            print(
                f"[send] 失败 attempt={attempt+1}/{retries}"
                f"{' [风控]' if risk else ''}: {e}"
            )
            if risk:
                return False
            if attempt + 1 < retries:
                jitter_sleep(delay)
    if last_err:
        print(f"[send] 最终失败: {last_err}")
    return False
