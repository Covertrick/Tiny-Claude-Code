# 架构

QQ 是适配器。核心是 Harness Runtime：一次用户消息对应一次 Run，工具调用进 intent 账本，技能按契约和沙箱执行。

```text
QQ Adapter (channel/)
        │  UserEvent
        ▼
Harness Runtime (agent/harness/)
  ├─ Run / Session          状态机，崩溃后可标 UNKNOWN
  ├─ Intent 账本            STARTED 先落盘，再执行
  ├─ Skill 注册表           只扫 manifest，按需加载，引用计数，版本快照
  ├─ 沙箱                   none / AST(L1) / 子进程(L2)
  └─ 约束演进               guardrails 执行期生效，回放对照后才晋升，可按快照回滚
        │
        ▼
Skills
  ├─ 内置：记忆、文件、催办、搜索、Vault（tools/qq.py + 契约表）
  └─ 插件：plugins/*/manifest.yaml
        │
        ▼
Trace /metrics
  run_success_rate · unknown_rate · sandbox_kill_count
  GET /harness/runs/{run_id}
```

## 依赖方向

- `channel/` 只负责收发、限流、把文本交给 `run_qq_agent`。
- `agent/harness/` 不解析 OneBot 字段。
- 领域包（`knowledge/`、`files/`、`vault/`、`schedules/`）不直接发 QQ 消息。

## 一次调用实际走过的路

1. `run_qq_agent` 打开 Run，冻结当时的技能版本和 `harness_rev`。
2. `agent_loop` 调模型。要执行工具时先写 intent 为 STARTED。
3. 若该 Run 的 guardrails 写了「不可逆禁止自动重试」，同一参数的失败/未知调用不会再执行。
4. `sandbox_policy` 决定在进程内调用、L1 或 L2。
5. `postconditions.py` 若定义了 `check(result)`，在 L1 里验证输出。
6. 账本记下成功、失败或 UNKNOWN，以及沙箱用量。
7. 进程重启时，停在 STARTED 的不可逆技能标成 UNKNOWN，并给用户一句确认，不自动重做。

## 落盘 `agent/.runtime/qq/`

| 路径 | 内容 |
|------|------|
| `harness/runs/*.json` | Run 与 intent 账本 |
| `harness/guardrails.md` | 当前已生效约束 |
| `harness/postconditions.py` | 输出检查 |
| `harness/snapshots/` | 可回滚的约束快照 |
| `harness/evolve_log.jsonl` | 晋升 / 丢弃 / 回滚记录 |
| `memory/` `files.db` `vault.db` `vector/` | 领域数据 |

## 明确不在这条链上的东西

Coding CLI（`python -m agent.main`）仍走原来的工具循环，不进入 QQ 的 Run 账本。不要把 bash / 改文件能力挂进 QQ。
