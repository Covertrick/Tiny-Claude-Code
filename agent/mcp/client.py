"""进程内 MCP 客户端：tools/list + tools/call 的轻量替身。"""

from __future__ import annotations

from collections.abc import Callable


class MCPClient:
    """一个已连接的 MCP 服务器：工具定义 + 本地 handlers。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: list[dict] = []
        self._handlers: dict[str, Callable] = {}

    def register(
        self,
        tool_defs: list[dict],
        handlers: dict[str, Callable],
    ) -> None:
        names = [tool.get("name") for tool in tool_defs]
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError("每个 MCP 工具都需要非空 name")
        if len(set(names)) != len(names):
            raise ValueError(f"服务器 {self.name!r} 存在重复工具名")
        missing = [name for name in names if name not in handlers]
        if missing:
            raise ValueError(f"缺少 MCP handlers: {', '.join(missing)}")
        self.tools = list(tool_defs)
        self._handlers = dict(handlers)

    def call_tool(self, tool_name: str, args: dict) -> str:
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return str(handler(**args))
        except Exception as exc:
            return f"MCP error: {type(exc).__name__}: {exc}"
