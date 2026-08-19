"""Hook 总线：注册 / 触发生命周期回调。"""

from typing import Any

HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}


def register_hook(event: str, callback) -> None:
    """把 callback 挂到指定事件（UserPromptSubmit / PreToolUse / PostToolUse / Stop）。"""
    HOOKS[event].append(callback)


def trigger_hook(event: str, *args) -> Any | None:
    """按注册顺序触发事件上的 hook。

    某个 callback 返回非 None 时短路，把该值交给调用方（常用于拦截工具）。
    """
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


def _register_defaults() -> None:
    """注册内置权限、日志、大输出警告与 Stop 统计。"""
    from .permission import (
        context_inject_hook,
        large_output_hook,
        log_hook,
        permission_hook,
        summary_hook,
    )

    register_hook("UserPromptSubmit", context_inject_hook)
    register_hook("PreToolUse", permission_hook)
    register_hook("PreToolUse", log_hook)
    register_hook("PostToolUse", large_output_hook)
    register_hook("Stop", summary_hook)


_register_defaults()

__all__ = ["HOOKS", "register_hook", "trigger_hook"]
