"""日历：从催办导出 ICS；Google/Outlook 双向同步预留接口。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def schedules_to_ics(*, user_id: str, out_path: Path | None = None) -> str:
    """把当前用户 pending 任务导出为 ICS 文本（可导入 Google/Outlook）。"""
    from agent.config import QQ_RUNTIME, ensure_runtime_dirs
    from agent.schedules import get_schedule_store

    items = get_schedule_store().list_for_user(
        user_id=user_id, tasks_only=True, include_done=False
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TinyQQAgent//ZH",
        "CALSCALE:GREGORIAN",
    ]
    for s in items:
        uid = f"{s.id}@tiny-qq-agent"
        due = (s.due_at or "").replace("-", "").replace(":", "")[:15]
        if not due:
            continue
        if "T" not in (s.due_at or ""):
            due = due[:8]
            dt_line = f"DTSTART;VALUE=DATE:{due[:8]}"
        else:
            # 简化：当 UTC 戳
            dt_line = f"DTSTART:{due}Z" if due.endswith("Z") or len(due) >= 15 else f"DTSTART:{due}"
        title = (s.title or "待办").replace("\n", " ")[:80]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            dt_line,
            f"SUMMARY:{title}",
            f"DESCRIPTION:category={s.category} status={s.status}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    text = "\r\n".join(lines) + "\r\n"
    if out_path is None:
        ensure_runtime_dirs()
        out_path = QQ_RUNTIME / "exports" / f"calendar_{user_id}.ics"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return str(out_path)


def google_calendar_sync_stub() -> str:
    """双向同步占位：需 OAuth 客户端，见 docs/roadmap。"""
    return (
        "Google/Outlook 双向同步尚未接线。"
        "可先用「导出日历」生成 ICS 导入；OAuth 同步见 docs/roadmap.md。"
    )
