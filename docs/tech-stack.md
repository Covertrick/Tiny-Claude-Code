# 技术栈

| 层级 | 选型 | 备注 |
|------|------|------|
| 包结构 | 单一 `agent/` | channel → core → tools.qq |
| QQ 桥 | NapCat / OneBot v11 | 正向 WebSocket |
| 推理 | DeepSeek + `agent.core.loop` | QQ 注入专用工具 |
| 催办 | APScheduler DateTrigger + SQLite | 24h 装载窗口 |
| 群缓存 | 内存 deque | 未 @ 不调模型 |
| 记忆 | JSONL + 哈希向量 | `memory/private_*` · `group_*` |
| 并发 | `threading.Semaphore` + 用户冷却 | `QQ_AGENT_CONCURRENCY` |
| 群文件 | SQLite `file_index` + 本地 groups/ | 仅 @ 时 LLM 一句话摘要 |
| 语音 | NapCat 转写字段 | 无 Whisper |
| 发送 | safe_send 重试/分片/引用 | 同步版 |
| 依赖 | requests, python-dotenv, PyYAML, websocket-client, APScheduler | |

## 刻意后置

| 项 | 原因 |
|----|------|
| 全面 asyncio | 先绞杀同步边界；WS 线程模型够用 |
| Redis | 单机无多进程粘滞需求 |
| Chroma | 哈希向量已够演示隔离与召回 |

配置见 `agent/.env` / `agent/config.py`（`QQ_*` / `ONEBOT_*` / `QQ_AGENT_CONCURRENCY`）。
