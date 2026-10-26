# 路线图

## 叙事定位（2026-10 起）

本项目按 **Agent Harness Runtime** 建设：QQ 是 Adapter，领域能力是 Skill。  
详细计划见 **[harness-runtime-plan.md](./harness-runtime-plan.md)**（唯一优先级来源）。

应用层功能（记忆 / 文件 / Vault / 催办等）**暂停堆新需求**，深度投入 Runtime。

---

## 已完成 Phase 1–5（应用层与基建）

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1–4 | 记忆分层 · 生活助手 · 插件骨架 · Vault · Dashboard · 意图门控 | ✅ |
| 4.5 | 文件智能标签 · 画像 harvest · 队列 · usage · ICS | ✅ |
| 5 | httpx 连接池 · 强制语义 · sqlite-vec · 搜索空结果回应 | ✅ |

---

## Phase 6 —— Harness Runtime（当前主线）

| 优先级 | 内容 | 状态 |
|--------|------|------|
| **P0** | Session/Run 状态机 · Skill 契约（effect_class）· intent 账本 · UNKNOWN 恢复 | ✅ |
| **P1** | 自描述注册表 · 版本快照 · 可逆卸载 · L2 进程沙箱 | ✅ |
| **P2** | 失败 trace 自改进 · Behavior Diff · 快照回滚 | ✅ |
| **P3** | Run Trace / 回放面板 · unknown_rate 等指标 | ✅ |

后置（与承重墙无关，不抢优先级）：

- Google Calendar / Outlook OAuth  
- PDF/图片 OCR  
- 插件市场与远程热更新  
- OneBot / NapCat 全程 asyncio 重写  
