# 整体架构

单一 Python 包 `agent/`：QQ 是频道，推理共用 `agent.core.loop`。

## 三层单向依赖（绞杀者）

```text
channel/  →  core/  →  tools/qq.py
   │           │            │
   │           │            ├─ knowledge/（多租户目录）
   │           │            ├─ schedules/ + scheduler.py
   │           │            └─ user_files / search
   └─ OneBot 收发 / 群缓存 / 拦截 / 会话
```

- **channel**：听/说 QQ，不直接碰 LLM HTTP  
- **core**：唯一 `agent_loop`；频道传入 `tools`+`handlers` 即不装 Coding 工具池  
- **tools/qq**：QQ 专用工具面；**禁止** bash / edit / Task DAG / MCP  

Coding CLI（`python -m agent.main`）仍走完整工具池，与 QQ 路径隔离。

## 模块拆分

```text
agent/
  config.py           # API + OneBot + MEMORY_DIR / AGENT_CONCURRENCY
  __main__.py         # python -m agent → QQ Agent
  main.py             # Coding CLI（可选）
  core/               # LLM / agent_loop / execute
  channel/            # QQ 协议与路由
    onebot.py · router.py · group_cache.py · intercept.py
    session.py · prompts.py · run.py
  tools/
    qq.py             # QQ 工具（记忆/催办/文件/搜索）
    …                 # Coding 工具（仅 CLI）
  knowledge/          # memory/private_{uid}/ · group_{gid}/
  files/              # 群文件 file_index + 摘要流水线
  schedules/          # SQLite 任务 list + 多点催办规则
  scheduler.py        # APScheduler DateTrigger + 早报
  user_files.py       # files/{user_id}/ 沙箱
  channel/send.py     # safe_send 重试/分片/引用
  channel/health.py   # WS 健康 + Server酱/SMTP
  channel/proactive.py# 早报 + 关键词
```

## 系统图

```mermaid
flowchart LR
  U[QQ用户] --> NC[NapCat]
  NC <-->|OneBot| CH[agent.channel]
  CH -->|@/私聊 + 信号量| LOOP[agent.core.loop]
  LOOP --> DS[DeepSeek]
  LOOP --> TOOLS[agent.tools.qq]
  TOOLS --> KB[knowledge 多租户]
  TOOLS --> SCH[schedules]
  CRON[scheduler] --> SCH
  CRON -->|到点 0Token| CH
```

## 数据落盘

`agent/.runtime/qq/`：

| 路径 | 用途 |
|------|------|
| `memory/private_{uid}/` · `memory/group_{gid}/` | 多租户长期记忆 |
| `sessions/` | 短期对话 |
| `schedules.db` | 任务 + 催办 tick |
| `files.db` · `files/groups/{gid}/` | 群文件索引与落盘 |
| `files/{user_id}/` | 用户下载沙箱 |
| `vector/` | 旧目录（启动时迁移到 memory/） |

## 本机限制

Windows 睡眠/关机 → 催办暂停；非伪 Multi-Agent / LangGraph。  
全面 asyncio + Redis + Chroma：**后置**（单机 NapCat 收益有限）。
