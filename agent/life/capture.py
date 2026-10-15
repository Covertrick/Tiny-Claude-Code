"""零摩擦闪念笔记：捕获 / 列表 / 检索。"""

from __future__ import annotations

import re

from agent.knowledge import get_knowledge_store

_TAGS = {
    "灵感": re.compile(r"灵感|想法|点子|idea", re.I),
    "工作": re.compile(r"工作|开会|项目|deadline|任务", re.I),
    "生活": re.compile(r"生活|家里|健身|旅行|爬山", re.I),
    "消费": re.compile(r"花了|买了|元|块钱|￥|¥", re.I),
}


def classify(text: str) -> str:
    for label, pat in _TAGS.items():
        if pat.search(text or ""):
            return label
    return "灵感"


def quick_capture(*, user_id: str, text: str, group_id: str = "private") -> str:
    text = (text or "").strip()
    if not text:
        return "空内容，没记。"
    tag = classify(text)
    rec = get_knowledge_store().remember(
        user_id=user_id,
        group_id=group_id,
        text=text,
        source="quick_capture",
        kind="note",
        title=f"闪念·{tag}",
        layer="episodic",
        metadata={"life_tag": tag},
    )
    return f"已记下（{tag}）id={rec.id}"


def list_notes(*, user_id: str, tag: str = "", limit: int = 15) -> str:
    store = get_knowledge_store()
    with store._lock:
        rows = [
            r
            for r in store._records
            if str(r.user_id) == str(user_id)
            and not r.archived
            and r.source == "quick_capture"
        ]
    if tag:
        rows = [r for r in rows if (r.metadata or {}).get("life_tag") == tag]
    rows = list(reversed(rows))[:limit]
    if not rows:
        return "还没有闪念。可以说「记一下 xxx」。"
    lines = [f"最近闪念（{len(rows)}）："]
    for r in rows:
        tag_s = (r.metadata or {}).get("life_tag") or "?"
        lines.append(f"- [{r.id}] ({tag_s}) {r.text[:80]}")
    return "\n".join(lines)


def search_notes(*, user_id: str, query: str, limit: int = 8) -> str:
    hits = get_knowledge_store().recall(
        user_id=user_id, query=query, top_k=limit
    )
    notes = [
        (r, s)
        for r, s in hits
        if r.source == "quick_capture" or "闪念" in (r.title or "")
    ]
    if not notes:
        # 放宽：任意命中
        notes = hits[:limit]
    if not notes:
        return f"没找到和「{query}」相关的闪念。"
    lines = [f"闪念检索「{query}」："]
    for r, s in notes:
        lines.append(f"- [{r.id}] {r.text[:100]}（{s:.2f}）")
    return "\n".join(lines)
