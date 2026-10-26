"""自修改白名单。权限、effect_class、沙箱实现、Adapter 协议不在此列。"""

from __future__ import annotations

EDITABLE = frozenset(
    {
        "guardrails.md",
        "skill_notes.md",
        "postconditions.py",
    }
)

_FORBIDDEN_MARKERS = (
    "effect_class",
    "sandbox_policy",
    "permissions",
    "adapter",
    "onebot",
)


def assert_editable(name: str, text: str) -> None:
    if name not in EDITABLE:
        raise PermissionError(f"禁止自修改：{name}")
    lowered = (text or "").lower()
    for marker in _FORBIDDEN_MARKERS:
        if marker in lowered and name == "postconditions.py":
            raise PermissionError(f"postconditions 不得改写 {marker}")
