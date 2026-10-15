"""文件自动标签：轻量规则，不烧 Token。"""

from __future__ import annotations

import re

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("发票", re.compile(r"发票|invoice|收据|报销", re.I)),
    ("合同", re.compile(r"合同|协议|contract|agreement", re.I)),
    ("简历", re.compile(r"简历|resume|cv", re.I)),
    ("代码", re.compile(r"\.(py|js|ts|java|go|rs|cpp|c|h)$|代码|source", re.I)),
    ("表格", re.compile(r"\.(xlsx?|csv)$|表格|报表", re.I)),
    ("文档", re.compile(r"\.(docx?|pdf|txt|md)$|文档|说明", re.I)),
    ("图片", re.compile(r"\.(png|jpe?g|gif|webp|bmp)$|截图|图片", re.I)),
    ("财务", re.compile(r"财务|账单|工资|报销|budget", re.I)),
]


def auto_tags(*, file_name: str, summary: str = "", extra: str = "") -> str:
    blob = f"{file_name} {summary} {extra}"
    hit = []
    for label, pat in _RULES:
        if pat.search(blob):
            hit.append(label)
    # 扩展名兜底
    if "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower()
        if ext and ext not in hit:
            hit.append(ext)
    # 去重保序
    seen = set()
    out = []
    for t in hit:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out[:8])
