# Tiny-Claude-Code

一个精简版的本地 Coding Agent：通过 **OpenAI 兼容**的 `/chat/completions` 接口（如阿里云百炼）驱动模型，在本地执行工具、做权限校验、管理待办，并支持 **SubAgent** 委派。

## 功能概览

| 能力 | 说明 |
|------|------|
| 基础工具 | `bash` / `read` / `write` / `edit` / `glob` |
| 任务规划 | `todo_write`：结构化待办，限制同时只能有一个 `in_progress` |
| Hooks | `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` |
| 权限 | 黑名单硬拦、危险命令询问、工作区外路径询问 |
| SubAgent | `task`：独立对话上下文执行子任务，只把最终文本交回父 Agent |
| 提醒 | 连续 3 轮未更新 todo 时注入 `<reminder>` |

## 目录结构

```text
Tiny-Claude-Code/
├── Agent/
│   ├── agent.py      # 主程序
│   └── .env          # 本地密钥
├── .gitignore
└── README.md
```

## 环境要求

- Python 3.10+（推荐 3.12 / 3.13）
- 依赖：`requests`、`python-dotenv`

```bash
pip install requests python-dotenv
```

## 配置

在 `Agent/` 下创建 `.env`（已被 gitignore）：

```env
API_KEY=你的密钥
BASE_URL=https://你的兼容端点/compatible-mode/v1
MODEL_NAME=你的模型名
```

程序会请求：

```text
{BASE_URL}/chat/completions
```

## 运行

在项目根目录执行（工作目录即 Agent 的 `WORKDIR`）：

```bash
cd Tiny-Claude-Code
python Agent/agent.py
```

- 输入任务后回车发送  
- 输入 `exit` 或空行退出  
- `Ctrl+C` 中断  

## 工具说明

### 父 Agent 可用

- **bash**：执行 shell（Windows 下为 cmd；输出会尝试 UTF-8 / GBK 解码）
- **read / write / edit / glob**：文件读写与查找（限制在工作目录内）
- **todo_write**：覆盖式更新整份任务列表
- **task**：启动 SubAgent，参数为任务描述字符串

### SubAgent

- 使用独立 `messages` + `SUB_SYSTEM_PROMPT`
- 仅有基础工具（**没有** `task` / `todo_write`，避免套娃与污染父待办）
- 结束后通过 `extract_text` 只返回最终总结给父 Agent

## 架构示意

```text
User
  │
  ▼
UserPromptSubmit hook
  │
  ▼
┌──────────── Parent agent_loop ────────────┐
│  LLM  ←→  execute_tool (hooks + handler)  │
│         ├─ bash/read/write/edit/glob      │
│         ├─ todo_write                     │
│         └─ task ──► SubAgent loop         │
│                      (fresh messages)     │
│                      └─ final text only   │
│  3 rounds w/o todo → <reminder>           │
└───────────────────────────────────────────┘
```

`execute_tool` 统一封装：`PreToolUse` → 执行 → `PostToolUse`。

## 权限要点

- **硬拦**（示例）：`sudo`、`shutdown`、`rm -rf /` 等  
- **询问**：含 `rm `、`C:\Windows` 等可疑片段，或读写工作区外路径  
- 黑名单为简单字符串匹配，不能替代完整沙箱；请在可信环境使用  

## 简单测试

```text
# 普通工具
用 glob 列出 Agent 下的 py 文件

# Todo 多步
创建 Agent/demo.txt 写入 hello，读回确认，并用 todo_write 跟踪进度

# 强制 SubAgent
必须调用 task：让子代理 glob 查找 Agent/*.py，返回不超过 5 行中文总结；不要自己直接 glob
```

## License

按仓库实际许可为准；若未声明，默认仅供学习交流。
