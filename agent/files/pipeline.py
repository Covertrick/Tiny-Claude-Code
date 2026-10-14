"""文件入库流水线：下载 +（仅 @ 时）一句话摘要 + SQLite 索引。"""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests

from agent.channel.group_cache import GROUP_CACHE
from agent.core.llm import chat
from agent.files.index import FileIndexStore, FileRecord, get_file_index


def summarize_file(*, file_name: str, group_context: str) -> str:
    """唯一烧 Token 的文件路径：一句话摘要。失败则退回文件名描述。"""
    system = (
        "你是一个文件助理。请根据文件名和当前群聊的上下文，"
        "用一句话总结这个文件的内容与用途。只输出那一句话，不要引号。"
    )
    user = (
        f"文件名：{file_name}\n"
        f"群聊记录：\n{group_context or '（无）'}"
    )
    try:
        msg = chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=None,
            max_tokens=80,
            timeout=60,
        )
        text = (msg.get("content") or "").strip()
        return text[:200] if text else f"群文件：{file_name}"
    except Exception as e:
        print(f"[files] 摘要失败: {e}")
        return f"群文件：{file_name}"


def _download(url: str, dest: Path) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        # 可能是本地 path
        src = Path(url)
        if src.is_file():
            shutil.copy2(src, dest)
            return True
        return False
    try:
        with requests.get(url, stream=True, timeout=90) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                for chunk in resp.iter_content(65536):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as e:
        print(f"[files] 下载失败 {url[:80]}: {e}")
        return False


def ingest_one(
    *,
    segment: dict[str, str],
    group_id: str,
    uploader_id: str,
    summarize: bool,
    group_context: str = "",
    store: FileIndexStore | None = None,
) -> FileRecord:
    store = store or get_file_index()
    name = segment.get("name") or "file.bin"
    dest = store.dest_path(group_id, name)
    url = segment.get("url") or ""
    path = segment.get("path") or ""
    local = ""
    if _download(url, dest) or (path and _download(path, dest)):
        local = str(dest)
    elif path and Path(path).is_file():
        shutil.copy2(path, dest)
        local = str(dest)

    summary = ""
    tags = ""
    if summarize:
        ctx = group_context or GROUP_CACHE.snapshot(group_id, limit=10)
        summary = summarize_file(file_name=name, group_context=ctx)
        tags = name.rsplit(".", 1)[-1] if "." in name else ""

    return store.add(
        group_id=group_id,
        uploader_id=uploader_id,
        file_name=name,
        local_path=local,
        summary=summary,
        tags=tags,
    )


def ingest_file_segments(
    *,
    segments: list[dict[str, str]],
    group_id: str,
    uploader_id: str,
    summarize: bool,
    group_context: str = "",
) -> list[FileRecord]:
    if not segments:
        return []
    store = get_file_index()
    ctx = group_context
    if summarize and not ctx:
        ctx = GROUP_CACHE.snapshot(group_id, limit=10)
    return [
        ingest_one(
            segment=seg,
            group_id=group_id,
            uploader_id=uploader_id,
            summarize=summarize,
            group_context=ctx,
            store=store,
        )
        for seg in segments
    ]


def format_ingest_reply(records: list[FileRecord]) -> str:
    if not records:
        return ""
    lines = []
    for r in records:
        if r.summary:
            lines.append(f"已为你保存 {r.file_name}，摘要：{r.summary}")
        else:
            lines.append(f"已登记文件 {r.file_name}（未摘要，未 @ 不消耗 Token）")
    return "\n".join(lines)
