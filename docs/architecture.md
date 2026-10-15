# 整体架构

单一包 `agent/`：QQ 是频道，推理共用 `agent.core.loop`。

## 三层单向依赖

```text
channel/  →  core/  →  tools/qq.py
   │                      ├─ knowledge/（记忆·画像·harvest）
   │                      ├─ files/（资产库·NL 检索）
   │                      ├─ vault/ · schedules/ · life/
   │                      └─ search · calendar_sync
   └─ 队列 · 限流 · 意图门控 · admin
```

## 模块树

```text
agent/
  channel/     router · job_queue · intent · intercept · send
  core/        llm（usage hook）· loop
  knowledge/   store · synthesis · profile · harvest
  files/       pipeline · tags · nl_search · delivery · index
  vault/       watcher · writer · index
  observability/  logging · usage
  admin/       Magic Link · CRUD SPA · tunnel
  calendar_sync.py
```

## 数据落盘 `agent/.runtime/qq/`

记忆 JSONL · profile.json · sessions · schedules.db · files.db · vault.db · usage.db · exports/*.ics

## 后置

全量 asyncio、Calendar OAuth、sqlite-vec、OCR 缩略图。
