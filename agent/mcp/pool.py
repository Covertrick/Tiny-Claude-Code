"""把已连接 MCP 工具拼进父 Agent 的动态工具池（OpenAI function 格式）。"""

from __future__ import annotations

from collections.abc import Callable

from . import connect as mcp_connect
from .connect import MCP_HOST_POLICY, mcp_clients, normalize_mcp_name

def assemble_tool_pool(builtin_tools: list[dict], builtin_handlers: dict[str, Callable]) -> tuple[list[dict], dict[str, Callable]]:
    """把父 Agent 的内建工具和 MCP 工具拼进动态工具池（OpenAI function 格式）。"""

    tools = list(builtin_tools)
    handlers = dict(builtin_handlers)
    policies: dict[str, str] = {}
    origins = {
        item["function"]["name"]: f"built-in tool {item['function']['name']!r}"
        for item in tools
        if item.get("type") == "function"
    }

    for server_name, server in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in server.tools:
            raw_name = tool_def["name"]
            safe_tool = normalize_mcp_name(raw_name)
            prefixed = f"mcp__{safe_server}__{safe_tool}"

            if len(prefixed) > 64:
                raise ValueError(f"MCP 工具名 {prefixed!r} 太长，超过 64 字符限制")
            origin = f"MCP tool {raw_name!r} from {server_name!r}"
            if prefixed in origins:
                raise ValueError(f"MCP 工具名 {prefixed!r} 重复，已有 {origins[prefixed]}")
            

            #校验MCP Schema
            schema = tool_def.get("inputSchema", {})
            if not isinstance(schema, dict) or schema.get("type", "object") != "object":
                raise ValueError(f"无效 inputSchema: {origin}")

            origins[prefixed] = origin
            tools.append({
                "type": "function",
                "function": {
                    "name": prefixed,
                    "description": tool_def.get("description", ""),
                    "parameters": schema,
                }
            })
            handlers[prefixed] = (
                lambda *, client = server, tool = raw_name, **kwargs: client.call_tool(tool, kwargs)
            )
            policies[prefixed] = MCP_HOST_POLICY.get(
                (server_name, raw_name), "confirm"
            )
    # 就地更新，避免 pool 与 connect 各持一份 policies
    mcp_connect.mcp_tool_policies.clear()
    mcp_connect.mcp_tool_policies.update(policies)
    return tools, handlers

def mcp_system_addon() -> str:
    """已连接服务器时追加到 system prompt。"""
    if not mcp_clients:
        return ""
    names = ", ".join(mcp_clients)
    return (
        f"已连接 MCP 服务器: {names}。"
        "请使用对应的 mcp__服务器__工具名调用；"
        "未连接时先用 connect_mcp。"
    )

