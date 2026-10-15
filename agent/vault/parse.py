"""Markdown Frontmatter + 简易切片。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    raw = text or ""
    if not raw.startswith("---"):
        return {}, raw
    m = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$", raw)
    if not m:
        return {}, raw
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip("\"'")
        if key == "tags":
            # tags: [a, b] 或 tags: a, b
            val = val.strip("[]")
            meta[key] = [t.strip().strip("\"'") for t in re.split(r"[,，]", val) if t.strip()]
        else:
            meta[key] = val
    return meta, m.group(2)


def chunk_markdown(body: str, *, max_chars: int = 800, overlap: int = 80) -> list[str]:
    """按标题/段落切片，控制单块长度。"""
    body = (body or "").strip()
    if not body:
        return []
    # 先按二级标题拆
    parts = re.split(r"(?m)(?=^#{1,3}\s+)", body)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(buf) + len(part) + 1 <= max_chars:
            buf = f"{buf}\n\n{part}".strip() if buf else part
            continue
        if buf:
            chunks.append(buf)
        if len(part) <= max_chars:
            buf = part
        else:
            # 硬切
            start = 0
            while start < len(part):
                end = min(len(part), start + max_chars)
                chunks.append(part[start:end])
                if end >= len(part):
                    break
                start = max(0, end - overlap)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks or [body[:max_chars]]


def note_title(path: Path, meta: dict[str, Any], body: str) -> str:
    if meta.get("title"):
        return str(meta["title"])[:120]
    for line in (body or "").splitlines():
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()[:120]
    return path.stem[:120]
