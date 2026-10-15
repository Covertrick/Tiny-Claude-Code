"""文件发送与事后回捞：群内补登 + 图片降级直发，禁止驱用户私聊补发。"""

from __future__ import annotations

from pathlib import Path

import re

from agent.channel.file_cache import RECENT_FILES
from agent.files.index import FileRecord, get_file_index
from agent.files.pipeline import clean_caption, ingest_one

_IMAGE_EXT = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _display_name(r: FileRecord) -> str:
    name = (r.summary or "").strip()
    if not name or len(name) > 40 or name.startswith(("这是", "一张", "群文件")):
        fn = r.file_name or "文件"
        if re.fullmatch(r"[0-9a-fA-F]{8,}.*", fn):
            suf = ("." + fn.rsplit(".", 1)[-1]) if "." in fn else ""
            fn = "未命名文件" + suf
        name = fn
    return name


def _kind_label(r: FileRecord) -> str:
    return (
        "表情包"
        if re.search(r"\.(gif|png|jpg|jpeg|webp)$", r.file_name or "", re.I)
        else "文件"
    )


def list_user_files_human(
    user_id: str,
    *,
    group_id: str | None = None,
    is_group: bool = False,
    group_name: str = "",
    limit: int = 80,
) -> str:
    """给人看的文件列表。

    - 群聊：只列本群里该用户保存的
    - 私聊：列全部，按「私聊 / 各群」分组
    """
    records = get_file_index().list_for_user(user_id, limit=limit)
    if is_group and group_id:
        records = [r for r in records if str(r.group_id) == str(group_id)]
        if not records:
            return "这个群里你还没让我存过文件～"
        title = group_name.strip() or f"群{group_id}"
        lines = [f"本群（{title}）你保存的文件（{len(records)}）："]
        from agent.files.pipeline import format_file_meta

        for i, r in enumerate(records, 1):
            lines.append(
                f"{i}. {_display_name(r)}（{_kind_label(r)}）\n   {format_file_meta(r)}"
            )
        lines.append("要发可以说「把xxx发出来」或「把上次那个PDF发我」")
        return "\n".join(lines)

    if not records:
        return "你目前还没有保存过文件哦～"

    # 私聊总览：按来源分组
    private_items = [r for r in records if r.group_id == "private"]
    by_group: dict[str, list[FileRecord]] = {}
    for r in records:
        if r.group_id == "private":
            continue
        by_group.setdefault(str(r.group_id), []).append(r)

    lines = [f"你的全部文件（共 {len(records)} 个）："]
    if private_items:
        lines.append(f"【私聊】{len(private_items)} 个")
        from agent.files.pipeline import format_file_meta

        for i, r in enumerate(private_items, 1):
            lines.append(
                f"  {i}. {_display_name(r)}（{_kind_label(r)}） · {format_file_meta(r)}"
            )
    for gid, items in by_group.items():
        from agent.files.pipeline import format_file_meta

        lines.append(f"【群 {gid}】{len(items)} 个")
        for i, r in enumerate(items, 1):
            lines.append(
                f"  {i}. {_display_name(r)}（{_kind_label(r)}） · {format_file_meta(r)}"
            )
    if not private_items and not by_group:
        return "你目前还没有保存过文件哦～"
    lines.append("要发某个可以说「把xxx发出来」；删除说「删除 名字」")
    return "\n".join(lines)


def is_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXT


def send_local_media(client, *, path: str | Path, group_id: str | None, user_id: str) -> str:
    """优先图片/GIF 直发；失败再 upload_*_file。"""
    path = Path(path)
    if not path.is_file():
        return f"本地文件不存在：{path.name}"

    # 1) 图片直发（表情包体验最好）
    if is_image_path(path):
        seg = [{"type": "image", "data": {"file": str(path.resolve())}}]
        try:
            if group_id:
                client.send_group_msg(group_id, seg)
            else:
                client.send_private_msg(user_id, seg)
            return "已发出"
        except Exception as e:
            print(f"[files] 图片直发失败，改走文件上传: {e}")

    # 2) 群/私聊文件上传
    try:
        if group_id:
            client.upload_group_file(group_id, str(path), path.name)
        else:
            client.upload_private_file(user_id, str(path), path.name)
        return "已发出"
    except Exception as e:
        # 3) CQ file 段兜底
        try:
            seg = [{"type": "file", "data": {"file": str(path), "name": path.name}}]
            if group_id:
                client.send_group_msg(group_id, seg)
            else:
                client.send_private_msg(user_id, seg)
            return "已发出"
        except Exception as e2:
            print(f"[files] 发送失败: {e}; 兜底: {e2}")
            return "发送失败"


def recover_from_recent(
    *,
    group_id: str,
    user_id: str,
    caption: str = "",
    within_seconds: float = 300,
) -> FileRecord | None:
    """往前翻近期附件缓存，补登入库（群内自愈，不驱私聊）。"""
    recent = RECENT_FILES.recent(
        group_id, limit=5, within_seconds=within_seconds, uploader_id=user_id
    )
    if not recent:
        recent = RECENT_FILES.recent(
            group_id, limit=5, within_seconds=within_seconds
        )
    alias = clean_caption(caption)
    for item in recent:
        seg = RECENT_FILES.to_segment(item)
        try:
            rec = ingest_one(
                segment=seg,
                group_id=group_id,
                uploader_id=item.uploader_id or user_id,
                summarize=False,
                caption=alias or item.caption or "",
            )
        except Exception as e:
            print(f"[files] 回捞失败 {item.name}: {e}")
            continue
        if rec.local_path and Path(rec.local_path).is_file():
            print(f"[files] 事后回捞成功 id={rec.id} name={rec.file_name}")
            return rec
    return None


def search_send_or_recover(
    *,
    client,
    query: str,
    user_id: str,
    group_id: str | None,
) -> str:
    """检索 → 有文件就发；没有则回捞近期缓存再发。绝不让用户去私聊。"""
    from agent.files.nl_search import search_assets
    from agent.files.pipeline import format_file_meta

    hits = search_assets(query, user_id=user_id, group_id=group_id, limit=5)
    best: FileRecord | None = None
    if hits:
        best = next(
            (h for h in hits if h.local_path and Path(h.local_path).is_file()),
            None,
        )
        # 有索引无物理文件 → 尝试回捞补登
        if best is None and group_id:
            recovered = recover_from_recent(
                group_id=group_id, user_id=user_id, caption=query
            )
            if recovered:
                best = recovered
            else:
                tip = (
                    "再发一次给我，我立刻补存～"
                    if not group_id
                    else "本群再发一次，我立刻补存～"
                )
                return f"这张我印象里有，但文件丢了。{tip}"

    if best is None and group_id:
        best = recover_from_recent(
            group_id=group_id, user_id=user_id, caption=query
        )

    if best is None:
        if not group_id:
            return "没找到～可以说「有哪些文件」看看你的库，或再发一次让我记住。"
        return "没捞到～群里再发一次并说记住，下次就能秒甩。"

    result = send_local_media(
        client,
        path=best.local_path,
        group_id=group_id if group_id and group_id != "private" else None,
        user_id=user_id,
    )
    # 短确认 + 元数据；禁止哈希/内部 id
    if result.startswith("已发"):
        name = _display_name(best)
        return f"来~ {_kind_label(best)}「{name}」\n{format_file_meta(best, with_summary=True)}"
    return "没发出去，稍后再试。"
