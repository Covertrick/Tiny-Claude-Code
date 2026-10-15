# 逻辑流程

## 消息主路径

```mermaid
flowchart TD
  E[OneBot 事件] --> D{去重/冷却/忙?}
  D -->|丢弃| X[结束]
  D --> G{群未 @?}
  G -->|是| C[缓存+静默入库]
  G -->|@/私聊| Q[job_queue 入队]
  Q --> F{有附件?}
  F -->|是| IN[ingest 摘要标签]
  IN --> ACK[元数据回执]
  F -->|否| I[意图分类 LLM]
  I --> P[拼 Prompt<br/>画像+门控记忆]
  P --> L[agent_loop]
  L --> R[safe_send 引用回复]
  R --> H[后台 harvest 画像]
```

## 文件资产检索

```text
「把上次张三那个PDF发我」
  → nl_search 解析 类型=pdf / 最近
  → search_for_user 打分（文件名+摘要+标签）
  → 直发图片或 upload_file
  → 回执附带 类型·大小·时间·#标签
```

## 催办

```text
自然语言建催办 → schedule_reminder
  → SQLite 任务 + 多 tick
  → APScheduler DateTrigger
  → 到点 0 Token 私聊/群提醒
「导出日历」→ ICS 文件（可导入 Google/Outlook）
```
