"""Vault 路径安全校验 + 单文件/全库索引。"""

from __future__ import annotations

from pathlib import Path

from agent.config import VAULT_PATH
from agent.vault.index import get_vault_index
from agent.vault.parse import chunk_markdown, note_title, parse_frontmatter

_SKIP_DIRS = {".git", ".obsidian", "node_modules", ".trash", ".smart-env"}


def vault_root() -> Path | None:
    if not VAULT_PATH:
        return None
    p = Path(VAULT_PATH).expanduser().resolve()
    return p if p.is_dir() else None


def vault_enabled() -> bool:
    return vault_root() is not None


def safe_vault_path(rel_or_abs: str | Path) -> Path:
    """确保目标路径落在 Vault 根内，防路径穿越。"""
    root = vault_root()
    if root is None:
        raise ValueError("未配置 QQ_VAULT_PATH 或目录不存在")
    target = Path(rel_or_abs)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise ValueError(f"路径越界，拒绝写入: {target}") from e
    return target


def _rel(path: Path) -> str:
    root = vault_root()
    assert root is not None
    return str(path.resolve().relative_to(root)).replace("\\", "/")


def index_file(path: str | Path) -> str:
    root = vault_root()
    if root is None:
        return "Vault 未启用"
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        p = safe_vault_path(p)
    except ValueError as e:
        return str(e)
    if not p.is_file() or p.suffix.lower() != ".md":
        return f"跳过非 md：{p}"
    # 跳过隐藏目录
    try:
        rel_parts = p.resolve().relative_to(root).parts
    except ValueError:
        return "路径越界"
    if any(part in _SKIP_DIRS or part.startswith(".") for part in rel_parts[:-1]):
        get_vault_index().remove_file(_rel(p))
        return f"跳过系统目录：{_rel(p)}"

    text = p.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    title = note_title(p, meta, body)
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    chunks = chunk_markdown(body)
    n = get_vault_index().upsert_file(
        rel_path=_rel(p),
        title=title,
        tags=[str(t) for t in tags],
        chunks=chunks,
        mtime=p.stat().st_mtime,
    )
    return f"已索引 {_rel(p)} title={title!r} chunks={n}"


def remove_indexed(path: str | Path) -> None:
    root = vault_root()
    if root is None:
        return
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        p = p.resolve()
        rel = str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        return
    get_vault_index().remove_file(rel)


def reindex_vault(*, limit: int = 5000) -> str:
    root = vault_root()
    if root is None:
        return "Vault 未启用：请设置 QQ_VAULT_PATH"
    count = 0
    for p in root.rglob("*.md"):
        if count >= limit:
            break
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        try:
            index_file(p)
            count += 1
        except Exception as e:
            print(f"[vault] 索引失败 {p}: {e}")
    stats = get_vault_index().stats()
    return f"全库扫描完成 files≈{count} indexed={stats}"
