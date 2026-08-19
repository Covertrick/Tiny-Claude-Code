# Tiny-Claude-Code

精简版本地 Coding Agent：通过 **OpenAI 兼容**的 `/chat/completions`（如阿里云百炼、OpenAI）驱动模型，在本地执行工具、做权限校验、管理待办，并支持 SubAgent、按需加载技能、上下文压缩与**跨会话长期记忆**。

## 功能概览

| 能力 | 说明 |
|------|------|
| 基础工具 | `bash` / `read` / `write` / `edit` / `glob` |
| 任务规划 | `todo_write`：覆盖更新待办，同时只能有一个 `in_progress` |
| Hooks | `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` |
| 权限 | 黑名单硬拦、危险命令询问、工作区外路径询问 |
| SubAgent | `task`：独立对话执行子任务，只把最终文本交回父 Agent |
| Skills | 系统提示只放目录；`load_skill` 按需读取 `skills/*/SKILL.md` |
| 压缩 | 大结果落盘、剪中间消息、旧 tool 占位；仍超限则 LLM 摘要 |
| **记忆** | 召回相关 `.md` 注入 system；对话结束自动提取；条数过多时 LLM 整合 |
| 提醒 | 连续 3 轮未更新 todo 时注入 `<reminder>` |

## 目录结构

```text
Tiny-Claude-Code/
├── skills/                      # 技能文档（给模型读的 SKILL.md）
│   ├── code-review/
│   ├── pdf/
│   └── mcp-builder/
├── agent/                       # Python 包
│   ├── main.py                  # CLI 入口
│   ├── config.py                # API / WORKDIR / RUNTIME_DIR
│   ├── core/
│   │   ├── llm.py               # chat/completions 封装
│   │   ├── execute.py           # PreToolUse → handler → PostToolUse
│   │   └── loop.py              # 父 Agent 主循环（含记忆召回 / 提取）
│   ├── tools/
│   │   ├── __init__.py          # TASK_TOOLS / TOOL_HANDLERS
│   │   ├── base.py              # bash/read/write/edit/glob
│   │   ├── todo.py
│   │   ├── task.py              # SubAgent（只用 BASE_TOOLS）
│   │   └── skill.py             # load_skill 入口
│   ├── hooks/                   # 生命周期与权限
│   ├── skill_load/              # SkillLoader、系统提示拼装
│   ├── compaction/              # 上下文压缩
│   ├── memory/                  # 长期记忆：落盘、召回、提取、整合
│   └── .env                     # 本地密钥（勿提交）
├── .gitignore
└── README.md
```

运行时还会生成（已 gitignore，不要提交）：

```text
agent/.runtime/transcripts/     # 压缩前对话归档
agent/.runtime/tool_results/    # 超大工具输出全文
agent/.runtime/memory/          # 长期记忆条目与 MEMORY.md 索引
```

仓库根目录若还有旧的 `.agent/` 或 `.memory/`，是以前跑出来的缓存，可手动删掉。

## 环境要求

- Python 3.10+（推荐 3.12 / 3.13）
- 依赖：`requests`、`python-dotenv`、`PyYAML`

```bash
pip install requests python-dotenv PyYAML
```

## 配置

在 `agent/` 下创建 `.env`（已被 gitignore）：

```env
API_KEY=你的密钥
BASE_URL=https://你的兼容端点/compatible-mode/v1
MODEL_NAME=你的模型名
```

`config.py` 会先读 `agent/.env`，再读当前目录的 `.env`。请求地址为：

```text
{BASE_URL}/chat/completions
```

- `WORKDIR`：启动时的当前工作目录（`Path.cwd()`），不是 `agent/` 本身
- `SKILLS_DIR`：`{WORKDIR}/skills`
- `RUNTIME_DIR`：`agent/.runtime/`（压缩归档、大输出、记忆）

## 运行

必须在**项目根目录**启动，否则扫不到 `skills/`，路径沙箱也不对：

```bash
cd Tiny-Claude-Code
python -m agent.main
```

- 输入任务后回车发送
- 输入 `exit` 或空行退出
- `Ctrl+C` 中断

## 工具说明

### 父 Agent

- **bash**：本地 shell（Windows 下为 cmd；输出尝试 UTF-8 / GBK）
- **read / write / edit / glob**：工作目录内的文件操作（`safe_path` 会先 `resolve` 再校验）
- **todo_write**：覆盖式更新整份任务列表
- **task**：启动 SubAgent，参数为任务描述
- **load_skill**：按技能名加载完整 `SKILL.md`

### SubAgent

- 独立 `messages` + `SUB_SYSTEM_PROMPT`
- 只有基础工具（**没有** `task` / `todo_write` / `load_skill`）
- 结束时只把最终文字交给父 Agent

## 长期记忆

记忆以 Markdown 文件落在 `agent/.runtime/memory/`，带 YAML frontmatter（`name` / `type` / `description`）+ 正文。索引文件为同目录下的 `MEMORY.md`。

### 类型（`MEMORY_TYPES`）

| type | 含义 |
|------|------|
| `user` | 用户长期偏好 |
| `feedback` | 重复出现的工作反馈 |
| `project` | 稳定的项目约定 |
| `reference` | 用户希望记住的外部资料 |

### 生命周期

```text
每轮 agent_loop 开始
  → load_memories：按最近用户话召回相关 .md
  → build_system：拼 system（技能约定 + 记忆目录 + 召回正文）
  → 更新 messages[0]

对话正常结束（无 tool_calls）
  → extract_memories：从对话提炼 persistent 记忆并写盘
  → 若有新记忆且条数 > CONSOLIDATE_THRESHOLD（默认 10）
      → consolidate_memories：LLM 合并重复、整库重写（带 snapshot 回滚）
```

### 设计要点

- **召回**：先让模型根据目录索引选条目（失败则关键词 fallback），再读全文注入 system
- **提取**：只存 `scope: persistent`；临时任务状态、`current_task`、重复内容会被过滤
- **整合**：删除旧 `.md` 后写入合并结果；失败则从 snapshot 恢复

### 测试记忆

```text
# 1. 写入：说一条明确的长期偏好
请记住：以后所有回复都用简体中文。这是长期偏好。

# 2. 检查落盘
dir agent\.runtime\memory
type agent\.runtime\memory\MEMORY.md

# 3. 召回：同会话或重启后再问
写注释和解释时用什么语言？
```

终端成功写入时会看到 `[提取记忆成功: 已存储 N 条记忆]`；整合成功时会看到 `[记忆整合成功: ...]`。

## 架构示意

```text
User
  │
  ▼
UserPromptSubmit hook
  │
  ▼
┌────────────── Parent loop.py ──────────────┐
│  memory: load_memories → build_system      │
│       ↓ 更新 messages[0]                   │
│  compaction.prepare                        │
│       ↓                                    │
│  core.llm.chat（带 TASK_TOOLS）             │
│       ↓                                    │
│  execute_tool（hooks + TOOL_HANDLERS）      │
│       ├─ bash/read/write/edit/glob         │
│       ├─ todo_write / load_skill           │
│       └─ task → tools/task.py 子循环       │
│  3 轮无 todo → <reminder>                  │
│  结束 → extract_memories → consolidate?    │
└────────────────────────────────────────────┘
```

模块依赖（单向，避免循环 import）：

```text
config
  → tools/base、skill_load、hooks、compaction、memory
  → core/execute、core/llm
  → tools/todo、tools/task、tools/skill
  → tools/__init__.py（登记表）
  → core/loop → main
```

`memory` 在运行时依赖 `skill_load.build_system_prompt` 拼基础 system；`core/loop` 在每轮开始召回、结束时提取。

压缩在每次请求模型前执行：大 tool 结果落盘 → 消息过多剪中间 → 旧结果改占位；仍超字符上限则摘要。API 若报上下文过长，再应急压缩并重试。

## 权限要点

- **硬拦**（示例）：`sudo`、`shutdown`、`rm -rf /` 等
- **询问**：含 `rm `、`C:\Windows` 等可疑片段，或读写工作区外路径
- 黑名单是字符串匹配，不能替代完整沙箱；请在可信环境使用

## 简单测试

```text
# 普通工具
用 glob 列出 agent 下的 py 文件

# Todo 多步
创建 agent/demo.txt 写入 hello，读回确认，并用 todo_write 跟踪进度

# 强制 SubAgent
必须调用 task：让子代理 glob 查找 agent/*.py，返回不超过 5 行中文总结；不要自己直接 glob

# 技能
按 code-review skill 审查 agent/config.py

# 记忆
请记住：本项目 agent 包在 agent/ 目录。这是长期项目约定。
然后问我 agent 代码在哪个目录。
```

## License

按仓库实际许可为准；若未声明，默认仅供学习交流。
