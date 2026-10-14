# 逻辑线路

## 消息分流

```mermaid
flowchart TD
  E[OneBot 消息] --> V[解析 text + 语音转写 + 文件段]
  V --> T{群/私聊}
  T -->|群未@| C[缓存转写文本 0Token]
  C --> F0[文件静默登记 无摘要]
  C --> K[关键词正则 → 私聊主人]
  T -->|群@或私聊| CD{用户冷却 3s?}
  CD -->|命中| SLOW[你慢点…]
  CD -->|通过| SEM{信号量}
  SEM --> FILE{@文件?}
  FILE -->|有且@| SUM[上下文+文件名一句话摘要 Token少]
  FILE -->|无| I{intercept?}
  SUM --> I
  I -->|待办| DB[schedules.db]
  I -->|否| A[core.loop + tools.qq]
  A --> SEND[safe_send 重试/分片/引用]
```

## 文件杀手锏

| 场景 | 行为 | Token |
|------|------|-------|
| 群友发文件未 @ | 下载/登记 file_index，无摘要 | 0 |
| 发文件并 @ | 拉近 10 条上下文 → 一句话摘要 → 落盘+SQLite | 极少 |
| 「把张三简历发我」 | `search_and_send_file` 模糊查 summary/tags | Agent 一轮 |

落盘：`agent/.runtime/qq/files/groups/{group_id}/` · 库：`files.db` 表 `file_index`。

## 催办 / 早报

- `schedule_reminder` → 多点 tick → APScheduler（0 Token）  
- 每日 `QQ_MORNING_BRIEF_HOUR` 私聊主人今日待办（查 SQLite，0 Token）  

## 入口

- `python -m agent`：QQ Agent  
- `python -m agent.main`：Coding CLI  
