"""登录态生命周期：异地登录 / 强制下线 → 停掉 Agent 全部进程。"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

_LOCK = threading.Lock()
_SHUTDOWN = threading.Event()
_REASON = ""
_HOOKS: list[Callable[[str], None]] = []


def is_shutting_down() -> bool:
    return _SHUTDOWN.is_set()


def shutdown_reason() -> str:
    return _REASON


def on_shutdown(cb: Callable[[str], None]) -> None:
    with _LOCK:
        _HOOKS.append(cb)


def request_shutdown(reason: str, *, exit_code: int = 0, hard: bool = True) -> None:
    """标记关机并执行钩子；默认硬退出整个进程树。"""
    global _REASON
    with _LOCK:
        if _SHUTDOWN.is_set():
            return
        _REASON = reason or "shutdown"
        _SHUTDOWN.set()
        hooks = list(_HOOKS)
    print(f"[lifecycle] 正在退出全部进程：{_REASON}")
    for cb in hooks:
        try:
            cb(_REASON)
        except Exception as e:
            print(f"[lifecycle] shutdown hook 失败: {e}")
    # 给钩子一点时间收尾
    time.sleep(0.3)
    if hard:
        os._exit(exit_code)


def is_kick_or_elsewhere_login(event: dict[str, Any]) -> str | None:
    """识别「别处登录 / 被踢下线」。命中返回可读原因，否则 None。"""
    if not isinstance(event, dict):
        return None

    post = str(event.get("post_type") or "")
    notice = str(event.get("notice_type") or "")
    sub = str(event.get("sub_type") or "")
    meta = str(event.get("meta_event_type") or "")
    offline_type = str(event.get("offline_type") or "")
    status = event.get("status") or {}

    blob = " ".join(
        str(x)
        for x in (
            post,
            notice,
            sub,
            meta,
            offline_type,
            event.get("message"),
            event.get("comment"),
        )
        if x
    ).lower()

    # go-cqhttp / NapCat：bot_offline
    if notice in ("bot_offline", "bot_offline_notice"):
        return f"机器人下线 notice={notice} sub={sub or offline_type or '-'}"

    # 客户端状态 / 强制下线
    if notice in ("client_status", "notify") and sub in (
        "offline",
        "kick",
        "logout",
        "disconnected",
    ):
        return f"客户端离线 notice={notice} sub={sub}"

    # lifecycle disable
    if post == "meta_event" and meta == "lifecycle" and sub in (
        "disable",
        "disconnect",
    ):
        return f"生命周期停用 sub={sub}"

    # heartbeat / status：online=false 且带 offline 语义时
    if isinstance(status, dict) and status.get("online") is False:
        # 避免误杀：仅当同时出现 kick / 异地相关字段
        if any(
            k in blob
            for k in ("kick", "elsewhere", "other", "挤", "下线", "offline")
        ):
            return "账号状态 online=false（疑似被挤下线）"

    # 文案兜底：别处登录 / 异地 / 挤下线
    keywords = (
        "别处登录",
        "异地登录",
        "在别处登录",
        "其他设备",
        "其它设备",
        "挤下线",
        "强制下线",
        "被踢",
        "logged in elsewhere",
        "another device",
        "kick",
    )
    for kw in keywords:
        if kw.lower() in blob:
            return f"检测到强制下线信号：{kw}"

    return None


def handle_event(event: dict[str, Any]) -> bool:
    """若为踢下线事件则触发关机，返回 True。"""
    reason = is_kick_or_elsewhere_login(event)
    if not reason:
        return False
    request_shutdown(reason, exit_code=0, hard=True)
    return True
