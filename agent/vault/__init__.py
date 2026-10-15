"""Obsidian / Markdown Vault：监听入库、检索、AI 写笔记 + Git。"""

from __future__ import annotations

from agent.vault.index import VaultIndex, get_vault_index
from agent.vault.sync import index_file, reindex_vault, safe_vault_path, vault_enabled
from agent.vault.watcher import start_vault_watcher, stop_vault_watcher
from agent.vault.writer import generate_and_write_note, search_vault

__all__ = [
    "VaultIndex",
    "get_vault_index",
    "vault_enabled",
    "safe_vault_path",
    "index_file",
    "reindex_vault",
    "start_vault_watcher",
    "stop_vault_watcher",
    "generate_and_write_note",
    "search_vault",
]
