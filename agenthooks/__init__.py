from typing import Any

HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}


def register_hook(event: str, callback) -> None:
    """注册Hook"""
    HOOKS[event].append(callback)


def trigger_hook(event: str, *args) -> Any | None:
    """触发Hook"""
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


def _register_defaults() -> None:
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
