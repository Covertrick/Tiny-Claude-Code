"""MCP：进程内 mock 发现与动态工具池。"""

from .connect import connect_mcp, get_mcp_policy, mcp_clients
from .pool import assemble_tool_pool, mcp_system_addon

__all__ = [
    "assemble_tool_pool",
    "connect_mcp",
    "get_mcp_policy",
    "mcp_clients",
    "mcp_system_addon",
]
