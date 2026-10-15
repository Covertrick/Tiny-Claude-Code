# 技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| 运行时 | Python 3.10+ / 同步为主 | 消息经 `job_queue` 多 worker；LLM/HTTP 走异步池 |
| QQ | NapCat + OneBot WS | websocket-client |
| LLM | DeepSeek OpenAI 兼容 | `httpx` AsyncClient 连接池；usage → `usage.db` |
| HTTP | httpx（统一连接池） | 搜索/抓取/LLM 共用；支持 `QQ_FETCH_PROXY` |
| 联网搜索 | DuckDuckGo API → HTML 回退 | 无结果也返回可转述中文说明 |
| 记忆 | JSONL + 向量索引 | fastembed（强制语义）/ 哈希回退；`*.vec.db` |
| 向量 | sqlite-vec（优先） | 扩展缺失 → SQLite BLOB + 余弦暴力 |
| 文件 | SQLite + SHA256 blob | NL 检索 + LLM 标签 |
| Vault | watchdog + Git | `vault.db` + 同步 `vault.vec.db` |
| 催办 | APScheduler + SQLite | ICS 导出 |
| 控制台 | FastAPI + Vue CDN | Magic Link + Cloudflare Tunnel |
| 可观测 | JSON 结构化日志 | Token 用量 /metrics（含 http / vector） |

## 主要环境变量

见 `agent/.env.example`：`API_KEY`、`QQ_ADMIN_*`、`QQ_VAULT_*`、`QQ_INTENT_GATE`、`QQ_FORCE_SEMANTIC`、`QQ_VECTOR_BACKEND`、`QQ_FETCH_PROXY`。

## 后置

OneBot 全程 asyncio 重写、Google Calendar OAuth、PDF OCR。
