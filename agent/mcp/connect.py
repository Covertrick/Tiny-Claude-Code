"""连接 MCP 服务器、规范化工具名、主机侧授权策略。"""

from __future__ import annotations

import re

from .client import MCPClient
from .servers import MOCK_SERVERS

mcp_clients: dict[str, MCPClient] = {}
mcp_tool_policies: dict[str, str] = {}

_DISALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9_-]")

# 授权来自主机配置，不来自服务器描述
MCP_HOST_POLICY = {
    ("docs", "search"): "allow",
    ("docs", "get_version"): "allow",
    ("deploy", "status"): "allow",
    ("deploy", "trigger"): "confirm",
}


def normalize_mcp_name(name: str) -> str:
    """把名字收成模型工具名可用字符。"""
    normalized = _DISALLOWED_CHARS.sub("_", name)
    if not normalized:
        raise ValueError("MCP 名称规范化后为空")
    return normalized


def connect_mcp(name: str) -> str:
    """连接 mock MCP 服务器并登记到 mcp_clients。"""
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS)
        return f"Unknown server '{name}'. Available: {available}"
    server = factory()
    mcp_clients[name] = server
    names = ", ".join(tool["name"] for tool in server.tools)
    print(f"  [mcp] connected: {name} -> {names}")
    return (
        f"Connected to MCP server '{name}'. "
        f"Discovered {len(server.tools)} tools: {names}"
    )


def get_mcp_policy(prefixed_name: str) -> str:
    """返回 allow / confirm；未知默认 confirm。"""
    return mcp_tool_policies.get(prefixed_name, "confirm")
