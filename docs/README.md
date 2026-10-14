# Tiny QQ Agent 文档索引

单一包 [`agent/`](../agent/)：OneBot 频道 + 自研 Agent Loop（多租户记忆、待办催办、搜索、文件）。

| 文档 | 内容 |
|------|------|
| [architecture.md](./architecture.md) | 三层依赖、绞杀边界、落盘 |
| [tech-stack.md](./tech-stack.md) | 技术栈与配置 |
| [logic-flow.md](./logic-flow.md) | 路由 / 催办 / 缓存逻辑 |
| [development.md](./development.md) | 开发、评价、简历表述 |
| [qq-setup.md](./qq-setup.md) | NapCat 接入 |

## 总体评价：值得做，但别一次吃完

| 点 | 评价 | 状态 |
|----|------|------|
| 三层单向依赖 + 绞杀者 | **强推**。`channel/` → `core/` → `tools/qq.py` 已按边界收紧 | ✅ 已落地 |
| 去掉 Coding 的 bash/edit/Task DAG（QQ 路径） | **强推**。QQ 场景不该挂写码工具 | ✅ `tools/qq` 白名单 + `use_mcp=False` |
| APScheduler + SQLite 催办 | 已基本到位，工具面收敛为 `schedule_reminder` | ✅ 已收敛 |
| 多租户记忆隔离 | **强推**。`memory/private_{uid}/` · `group_{gid}/` + scope 元数据 | ✅ 已落地 |
| 全面 asyncio + Redis + Chroma | **后置**。单机 NapCat 收益有限；先绞杀同步结构，再换运行时 | ⏸ 不做 |
| NapCat 语音转写（无 Whisper） | 强推，0 Token | ✅ `record.text` → 缓存 |
| 文件摘要索引 + search_and_send | 杀手锏；仅 @ 时烧极少 Token | ✅ |
| 早报 / 关键词主动提醒 | 0 Token | ✅ |
| safe_send / 冷却 / 健康告警 / 分片引用 | 生产底线 | ✅ |

并发用 `AGENT_CONCURRENCY` 信号量；冷却 `QQ_USER_COOLDOWN_SECONDS`；不引入 Redis。

## 启动

```bash
python -m agent              # QQ Agent（主入口）
python -m agent.demo         # 无 NapCat 终端演示
python -m agent.smoke_test   # 离线冒烟
python -m agent.main         # 原 Coding CLI（可选）
```
