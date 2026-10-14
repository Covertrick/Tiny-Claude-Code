"""QQ 文件沙箱：根目录钉死 FILES_DIR/{user_id}/，防路径穿越。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from agent.config import FILES_DIR, ensure_runtime_dirs


def _safe_name(name: str) -> str:
    name = unquote(name).strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\u4e00-\u9fff-]+", "_", name)
    return name or "file.bin"


def user_root(user_id: str) -> Path:
    """沙箱根：仅允许该用户目录。"""
    ensure_runtime_dirs()
    root = (FILES_DIR / str(user_id)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    files_root = FILES_DIR.resolve()
    if os.path.commonpath([str(root), str(files_root)]) != str(files_root):
        raise ValueError("非法用户根目录")
    return root


def user_dir(user_id: str, group_id: str | None = None) -> Path:
    """作用域目录：files/{user_id}/{group|private}/。"""
    scope = str(group_id) if group_id else "private"
    # 禁止 scope 里带穿越
    if "/" in scope or "\\" in scope or ".." in scope:
        raise ValueError("非法 group_id")
    base = (user_root(user_id) / scope).resolve()
    root = user_root(user_id)
    if os.path.commonpath([str(base), str(root)]) != str(root):
        raise ValueError("路径逃出用户沙箱")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _assert_in_sandbox(path: Path, user_id: str, group_id: str | None) -> Path:
    path = path.resolve()
    root = user_dir(user_id, group_id).resolve()
    if os.path.commonpath([str(path), str(root)]) != str(root):
        raise ValueError("路径穿越被拒绝")
    return path


def download_url(
    *,
    url: str,
    user_id: str,
    group_id: str | None = None,
    filename: str | None = None,
) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("只允许 http/https 下载")
    name = filename or Path(parsed.path).name or "download.bin"
    dest = _assert_in_sandbox(
        user_dir(user_id, group_id) / _safe_name(name), user_id, group_id
    )
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with dest.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    return dest


def list_files(user_id: str, group_id: str | None = None) -> list[str]:
    root = user_dir(user_id, group_id)
    return sorted(p.name for p in root.iterdir() if p.is_file())


def resolve_user_file(
    user_id: str, filename: str, group_id: str | None = None
) -> Path:
    return _assert_in_sandbox(
        user_dir(user_id, group_id) / _safe_name(filename), user_id, group_id
    )


def delete_file(user_id: str, filename: str, group_id: str | None = None) -> bool:
    path = resolve_user_file(user_id, filename, group_id)
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True
