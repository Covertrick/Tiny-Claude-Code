# 技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| 运行时 | Python 3.10+ / 同步为主 | 消息经 `job_queue` 多 worker |
| QQ | NapCat + OneBot WS | websocket-client |
| LLM | DeepSeek OpenAI 兼容 | usage 写入 `usage.db` |
| 记忆 | JSONL + 哈希/fastembed | 画像 `profile.json` |
| 文件 | SQLite + SHA256 blob | NL 检索 + LLM 标签 |
| Vault | watchdog + Git | `vault.db` 切片索引 |
| 催办 | APScheduler + SQLite | ICS 导出 |
| 控制台 | FastAPI + Vue CDN | Magic Link + Cloudflare Tunnel |
| 可观测 | JSON 结构化日志 | Token 用量 /metrics |

## 主要环境变量

见 `agent/.env.example`：`API_KEY`、`QQ_ADMIN_*`、`QQ_VAULT_*`、`QQ_INTENT_GATE`、`QQ_FETCH_PROXY`。

## 后置

全量 asyncio、连接池复用深化、Google Calendar OAuth、sqlite-vec。
