---
name: mcp-builder
description: 构建 MCP（Model Context Protocol）服务器，为模型增加新能力。在用户要创建 MCP 服务、添加工具或接入外部服务时使用。
---

# MCP 服务器构建 Skill

你现在具备构建 MCP（Model Context Protocol）服务器的能力。MCP 让模型通过标准协议与外部服务交互。

## MCP 是什么？

MCP 服务器可暴露：
- **Tools（工具）**：模型可调用的函数（类似 API）
- **Resources（资源）**：模型可读的数据（如文件或数据库记录）
- **Prompts（提示）**：预置的提示模板

## 快速开始：Python MCP 服务器

### 1. 项目初始化

```bash
# 创建项目
mkdir my-mcp-server && cd my-mcp-server
python3 -m venv venv && source venv/bin/activate

# 安装 MCP SDK
pip install mcp
```

### 2. 基础服务器模板

```python
#!/usr/bin/env python3
"""my_server.py - A simple MCP server"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Create server instance
server = Server("my-server")

# Define a tool
@server.tool()
async def hello(name: str) -> str:
    """Say hello to someone.

    Args:
        name: The name to greet
    """
    return f"Hello, {name}!"

@server.tool()
async def add_numbers(a: int, b: int) -> str:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number
    """
    return str(a + b)

# Run server
async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### 3. 注册到 Claude / 客户端

写入 `~/.claude/mcp.json`：
```json
{
  "mcpServers": {
    "my-server": {
      "command": "python3",
      "args": ["/path/to/my_server.py"]
    }
  }
}
```

## TypeScript MCP 服务器

### 1. 初始化

```bash
mkdir my-mcp-server && cd my-mcp-server
npm init -y
npm install @modelcontextprotocol/sdk
```

### 2. 模板

```typescript
// src/index.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server({
  name: "my-server",
  version: "1.0.0",
});

// Define tools
server.setRequestHandler("tools/list", async () => ({
  tools: [
    {
      name: "hello",
      description: "Say hello to someone",
      inputSchema: {
        type: "object",
        properties: {
          name: { type: "string", description: "Name to greet" },
        },
        required: ["name"],
      },
    },
  ],
}));

server.setRequestHandler("tools/call", async (request) => {
  if (request.params.name === "hello") {
    const name = request.params.arguments.name;
    return { content: [{ type: "text", text: `Hello, ${name}!` }] };
  }
  throw new Error("Unknown tool");
});

// Start server
const transport = new StdioServerTransport();
server.connect(transport);
```

## 进阶模式

### 接入外部 API

```python
import httpx
from mcp.server import Server

server = Server("weather-server")

@server.tool()
async def get_weather(city: str) -> str:
    """Get current weather for a city."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.weatherapi.com/v1/current.json",
            params={"key": "YOUR_API_KEY", "q": city}
        )
        data = resp.json()
        return f"{city}: {data['current']['temp_c']}C, {data['current']['condition']['text']}"
```

### 数据库访问

```python
import sqlite3
from mcp.server import Server

server = Server("db-server")

@server.tool()
async def query_db(sql: str) -> str:
    """Execute a read-only SQL query."""
    if not sql.strip().upper().startswith("SELECT"):
        return "Error: Only SELECT queries allowed"

    conn = sqlite3.connect("data.db")
    cursor = conn.execute(sql)
    rows = cursor.fetchall()
    conn.close()
    return str(rows)
```

### Resources（只读数据）

```python
@server.resource("config://settings")
async def get_settings() -> str:
    """Application settings."""
    return open("settings.json").read()

@server.resource("file://{path}")
async def read_file(path: str) -> str:
    """Read a file from the workspace."""
    return open(path).read()
```

## 测试

```bash
# 用 MCP Inspector 测试
npx @anthropics/mcp-inspector python3 my_server.py

# 或直接发送测试消息
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 my_server.py
```

## 最佳实践

1. **工具描述要清晰**：模型靠描述决定何时调用
2. **校验输入**：始终校验并清洗入参
3. **错误处理**：返回有意义的错误信息
4. **默认异步**：I/O 使用 async/await
5. **安全**：敏感操作必须鉴权，勿裸露
6. **幂等**：工具应可安全重试
