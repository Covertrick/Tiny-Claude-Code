"""自然语言文件检索：解析类型/时间词，增强 search_for_user 打分。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent.files.index import FileRecord, get_file_index


@dataclass
class NLQuery:
    raw: str
    tokens: list[str]
    filetype: str = ""  # pdf/image/doc/...
    want_recent: bool = False


_TYPE_MAP = [
    ("pdf", re.compile(r"pdf|PDF")),
    ("图片", re.compile(r"图|图片|表情包|截图|png|jpe?g|gif|webp", re.I)),
    ("文档", re.compile(r"文档|word|docx?|txt|md", re.I)),
    ("表格", re.compile(r"表格|excel|xlsx?|csv", re.I)),
    ("压缩包", re.compile(r"压缩|zip|rar|7z", re.I)),
]


def parse_nl_query(text: str) -> NLQuery:
    raw = (text or "").strip()
    # 去掉发送类动词
    cleaned = re.sub(
        r"(把|将|帮我|给我|发一下|发出来|发给我|调出来|找出|找一下|搜索)?",
        "",
        raw,
    )
    cleaned = re.sub(r"(那个|这个|上次|之前的?)", " ", cleaned)
    filetype = ""
    for label, pat in _TYPE_MAP:
        if pat.search(raw):
            filetype = label
            break
    want_recent = bool(re.search(r"上次|刚才|最近|刚刚", raw))
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_\-\.]{2,}", cleaned)
    # 去停用
    stop = {"文件", "附件", "发我", "出来", "一下", "那个", "这个"}
    tokens = [t for t in tokens if t not in stop]
    return NLQuery(raw=raw, tokens=tokens, filetype=filetype, want_recent=want_recent)


def search_assets(
    query: str,
    *,
    user_id: str,
    group_id: str | None = None,
    limit: int = 5,
) -> list[FileRecord]:
    nq = parse_nl_query(query)
    store = get_file_index()
    # 用解析后的 tokens 拼回查询串给现有检索
    q = " ".join(nq.tokens) if nq.tokens else query
    hits = store.search_for_user(q, user_id=user_id, group_id=group_id, limit=40)
    if not hits:
        hits = store.search_for_user(query, user_id=user_id, group_id=group_id, limit=40)

    def _boost(r: FileRecord) -> float:
        score = 0.0
        blob = f"{r.file_name} {r.summary} {r.tags}".lower()
        for t in nq.tokens:
            if t.lower() in blob:
                score += 2.0
        if nq.filetype:
            if nq.filetype == "pdf" and ".pdf" in (r.file_name or "").lower():
                score += 5.0
            elif nq.filetype == "图片" and re.search(
                r"\.(gif|png|jpe?g|webp)$", r.file_name or "", re.I
            ):
                score += 5.0
            elif nq.filetype in (r.tags or ""):
                score += 3.0
            elif nq.filetype.lower() in blob:
                score += 2.0
        if nq.want_recent:
            score += 0.5  # list 已按时间，再靠排序
        return score

    ranked = sorted(hits, key=_boost, reverse=True)
    if nq.want_recent and ranked:
        # 时间优先微调：同分取新
        ranked = sorted(
            ranked,
            key=lambda r: (_boost(r), r.create_time or ""),
            reverse=True,
        )
    return ranked[:limit]
