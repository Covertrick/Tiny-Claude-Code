"""AI 写笔记 → 安全落盘 → 索引 → Git。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from agent.config import VAULT_NOTES_SUBDIR
from agent.vault.gitops import commit_paths
from agent.vault.index import get_vault_index
from agent.vault.sync import index_file, safe_vault_path, vault_enabled, vault_root
from agent.vault.parse import parse_frontmatter


_GEN_SYS = """你是 Obsidian 笔记写手。根据用户主题写一篇简洁有用的中文 Markdown 笔记。
要求：
1. 第一行起必须是 YAML frontmatter，字段：title, tags（列表）, created, source: qq-agent
2. 正文用 ## 分节，口语清晰，适合个人知识库
3. 不要用 Markdown 代码围栏包住整篇；直接输出可保存的 .md 原文
4. 篇幅适中（约 400–900 字），别水文
"""


def _slug(topic: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", (topic or "").strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s or "note")[:48]


def _ensure_frontmatter(md: str, topic: str) -> str:
    text = (md or "").strip()
    # 去掉误包的 ```markdown
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    meta, body = parse_frontmatter(text)
    now = datetime.now().strftime("%Y-%m-%d")
    if not meta:
        title = topic.strip()[:80] or "未命名笔记"
        tags = ["qq-agent"]
        return (
            f"---\ntitle: {title}\ntags: [{', '.join(tags)}]\n"
            f"created: {now}\nsource: qq-agent\n---\n\n{text}\n"
        )
    if not meta.get("title"):
        meta["title"] = topic.strip()[:80] or "未命名笔记"
    if not meta.get("created"):
        meta["created"] = now
    meta["source"] = "qq-agent"
    tags = meta.get("tags")
    if not isinstance(tags, list):
        tags = ["qq-agent"]
    elif "qq-agent" not in tags:
        tags = list(tags) + ["qq-agent"]
    lines = ["---"]
    for k, v in meta.items():
        if k == "tags":
            lines.append(f"tags: [{', '.join(str(t) for t in tags)}]")
        else:
            lines.append(f"{k}: {v}")
    if "tags" not in meta:
        lines.append(f"tags: [{', '.join(str(t) for t in tags)}]")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + (body or "").strip() + "\n"


def generate_and_write_note(topic: str, *, extra: str = "") -> str:
    """根据主题生成笔记并写入 Vault。"""
    if not vault_enabled():
        return "Vault 未启用：请在 agent/.env 设置 QQ_VAULT_PATH=你的Obsidian库路径"
    topic = (topic or "").strip()
    if not topic:
        return "请告诉我笔记主题，例如「写一篇关于 Python 异步的笔记」"

    from agent.channel.trust import wrap_untrusted
    from agent.core.llm import chat

    user = f"主题：{topic}"
    if extra:
        user += f"\n补充要求：{extra}"
    try:
        msg = chat(
            [
                {"role": "system", "content": _GEN_SYS},
                {
                    "role": "user",
                    "content": wrap_untrusted("note_topic", user, max_len=2000),
                },
            ],
            tools=None,
            max_tokens=2000,
            timeout=90,
        )
        md = _ensure_frontmatter(str(msg.get("content") or ""), topic)
    except Exception as e:
        return f"生成笔记失败：{e}"

    day = datetime.now().strftime("%Y-%m-%d")
    rel = Path(VAULT_NOTES_SUBDIR) / f"{day}-{_slug(topic)}.md"
    try:
        target = safe_vault_path(rel)
    except ValueError as e:
        return str(e)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # 避免覆盖：加时分
        stamp = datetime.now().strftime("%H%M%S")
        target = safe_vault_path(
            Path(VAULT_NOTES_SUBDIR) / f"{day}-{_slug(topic)}-{stamp}.md"
        )
    target.write_text(md, encoding="utf-8")
    idx_msg = index_file(target)
    git_msg = commit_paths([target], f"docs: QQ Agent 笔记 — {topic[:60]}")
    root = vault_root()
    rel_s = str(target.relative_to(root)).replace("\\", "/") if root else str(target)
    return (
        f"已写入 Vault：{rel_s}\n"
        f"{idx_msg}\n"
        f"{git_msg}\n"
        f"在 Obsidian 里打开即可。"
    )


def search_vault(query: str, *, top_k: int = 5) -> str:
    if not vault_enabled():
        return "Vault 未启用：请设置 QQ_VAULT_PATH"
    hits = get_vault_index().search(query, top_k=top_k)
    if not hits:
        return "Vault 里没找到相关笔记（可先全库索引或检查监听是否在跑）"
    lines = []
    for h in hits:
        tag = f" #{' #'.join(h.tags)}" if h.tags else ""
        snippet = h.chunk.replace("\n", " ")[:160]
        lines.append(f"- {h.title}（{h.path}，{h.score:.2f}）{tag}\n  {snippet}")
    return "Vault 检索：\n" + "\n".join(lines)
