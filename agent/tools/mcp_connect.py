"""connect_mcp 工具：连接 mock MCP 并发现其工具。"""

from ..mcp import connect_mcp


def run_connect_mcp(name: str) -> str:
    return connect_mcp(name)


CONNECT_MCP_TOOL = {
    "type": "function",
    "function": {
        "name": "connect_mcp",
        "description": (
            "连接一个 MCP 服务器并发现其工具。"
            "可用: docs（文档搜索）、deploy（部署状态/触发）。"
            "连接后才能调用 mcp__docs__search 等工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": ["docs", "deploy"],
                    "description": "MCP 服务器名",
                },
            },
            "required": ["name"],
        },
    },
}
