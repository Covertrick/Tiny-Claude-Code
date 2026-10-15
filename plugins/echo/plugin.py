"""示例插件。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins.loader import PluginRegistry


def register(registry: PluginRegistry) -> None:
    registry.register_tool("plugin_echo", lambda text="": f"echo: {text}")
