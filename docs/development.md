# 开发说明

## 目录与边界

见 [architecture.md](./architecture.md)。

| 目录 | 职责 | 禁止 |
|------|------|------|
| `channel/` | 听/说 QQ、缓存、拦截、拼 Prompt、信号量 | 直接调 DeepSeek HTTP |
| `core/` | 统一 Agent Loop | 感知 QQ 协议细节 |
| `tools/qq.py` | QQ 工具白名单 | bash / edit / Task DAG / MCP |
| `knowledge/` | 多租户记忆目录 | 跨用户读写 |
| `schedules/` + `scheduler.py` | 任务 list + 本地催办 | 催办走 LLM |

## 运行

```bash
pip install -r requirements.txt
python -m agent.smoke_test
python -m agent.demo
# NapCat WS 就绪后
python -m agent
```

## 路线图（别一次吃完）

1. ~~三层绞杀 + QQ 去写码工具~~  
2. ~~多租户记忆目录~~  
3. ~~催办工具面 `schedule_reminder` + 信号量~~  
4. **后置**：asyncio 全链路、Redis 会话、Chroma 向量（有服务器再上）

## 简历表述（诚实）

**项目**：基于自研 Agent Loop 的 QQ 智能助手（OneBot / NapCat）

- 事件驱动 OneBot；频道与 Coding CLI 共用 loop，工具面隔离  
- 用户/群目录隔离记忆 + APScheduler 多点催办（0 Token）  
- 群未 @ 只缓存；@ 时滑动窗口按需进模型；并发信号量控压  

避免写：未实现的 Multi-Agent / LangGraph / Redis / Chroma / 7×24（除非已上服务器守护）。
