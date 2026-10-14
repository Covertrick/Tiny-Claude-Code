"""OneBot 消息段解析：文本 / @ / 语音转写 / 附件。

语音：依赖 NapCat「语音转文字」——record 段若带 text，或同条已有 text 段，
直接当纯文本用，不做 Whisper/STT（0 Token）。
"""

from __future__ import annotations

import re
from typing import Any


def extract_plain_text(message: Any) -> str:
    """仅纯文本（缓存用）；不含 @/附件占位。"""
    if isinstance(message, str):
        return re.sub(r"\[CQ:[^\]]+\]", "", message).strip()
    if not isinstance(message, list):
        return ""
    parts: list[str] = []
    for seg in message:
        if isinstance(seg, dict) and seg.get("type") == "text":
            parts.append(str((seg.get("data") or {}).get("text") or ""))
    return "".join(parts).strip()


def extract_voice_text(message: Any) -> str:
    """从 record 段提取 NapCat/QQ 内置转写文本。"""
    if isinstance(message, str):
        # CQ: [CQ:record,file=xxx,text=转写]
        m = re.search(r"\[CQ:record,[^\]]*text=([^\],]*)", message)
        return (m.group(1) if m else "").strip()
    if not isinstance(message, list):
        return ""
    parts: list[str] = []
    for seg in message:
        if not isinstance(seg, dict) or seg.get("type") != "record":
            continue
        data = seg.get("data") or {}
        # NapCat 常见字段：text / asr / transcription
        for key in ("text", "asr", "transcription", "recognize"):
            val = data.get(key)
            if val:
                parts.append(str(val).strip())
                break
    return " ".join(p for p in parts if p).strip()


def extract_cache_text(message: Any) -> str:
    """滑动窗口用：纯文本 + 语音转写（有则拼上）。"""
    plain = extract_plain_text(message)
    voice = extract_voice_text(message)
    if plain and voice and voice not in plain:
        return f"{plain} {voice}".strip()
    return plain or voice


def extract_file_segments(message: Any) -> list[dict[str, str]]:
    """提取 file（及可选 image 当附件）段：name / url / file_id。"""
    out: list[dict[str, str]] = []
    if isinstance(message, str):
        for m in re.finditer(
            r"\[CQ:(file|image),([^\]]+)\]", message, flags=re.I
        ):
            attrs = dict(
                re.findall(r"(\w+)=([^,\]]+)", m.group(2))
            )
            name = attrs.get("name") or attrs.get("file") or m.group(1)
            out.append(
                {
                    "kind": m.group(1).lower(),
                    "name": name,
                    "url": attrs.get("url") or "",
                    "file_id": attrs.get("file_id") or attrs.get("id") or "",
                    "path": attrs.get("path") or attrs.get("file") or "",
                }
            )
        return out
    if not isinstance(message, list):
        return out
    for seg in message:
        if not isinstance(seg, dict):
            continue
        kind = seg.get("type")
        if kind not in ("file", "image"):
            continue
        # 纯表情图常无业务文件名，image 仅当带明确 name/file 时收录
        data = seg.get("data") or {}
        name = str(data.get("name") or data.get("file") or "")
        if kind == "image" and not data.get("name"):
            continue
        if not name:
            name = kind
        out.append(
            {
                "kind": str(kind),
                "name": name,
                "url": str(data.get("url") or ""),
                "file_id": str(data.get("file_id") or data.get("id") or ""),
                "path": str(data.get("path") or data.get("file") or ""),
            }
        )
    return out


def extract_text(message: Any) -> str:
    """给 Agent 的可读文本：text + @ + 语音转写 + 附件占位。"""
    if isinstance(message, str):
        return message
    if not isinstance(message, list):
        return str(message or "")

    parts: list[str] = []
    for seg in message:
        if not isinstance(seg, dict):
            continue
        kind = seg.get("type")
        data = seg.get("data") or {}
        if kind == "text":
            parts.append(str(data.get("text") or ""))
        elif kind == "at":
            parts.append(f"@{data.get('qq') or ''}")
        elif kind == "record":
            voice = ""
            for key in ("text", "asr", "transcription", "recognize"):
                if data.get(key):
                    voice = str(data[key]).strip()
                    break
            if voice:
                parts.append(f"[语音转写]{voice}")
            else:
                parts.append("[语音]")
        elif kind in ("file", "image"):
            name = data.get("name") or data.get("file") or kind
            url = data.get("url") or data.get("path") or ""
            parts.append(f"[附件:{name} url={url}]")
    return "".join(parts)


def is_at_bot(message: Any, bot_qq: str) -> bool:
    bot_qq = str(bot_qq or "")
    if not bot_qq:
        return False
    if isinstance(message, list):
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "at":
                qq = str((seg.get("data") or {}).get("qq") or "")
                if qq == bot_qq or qq == "all":
                    return True
    return f"@{bot_qq}" in extract_text(message)


def strip_at(text: str, bot_qq: str) -> str:
    text = re.sub(rf"@{re.escape(str(bot_qq))}\s*", "", text)
    text = re.sub(r"@all\s*", "", text, flags=re.I)
    # 去掉附件/语音占位后留给 Agent 的纯意图
    text = re.sub(r"\[附件:[^\]]*\]", "", text)
    text = re.sub(r"\[语音转写\]", "", text)
    text = re.sub(r"\[语音\]", "", text)
    return text.strip()
