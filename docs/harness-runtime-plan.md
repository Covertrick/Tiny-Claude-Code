# Harness Runtime 演进计划

> **叙事骨架**：本项目不再按「QQ 机器人功能大全」描述，而按  
> **「以 QQ 为前端 Adapter、以 Harness Runtime 为核心、以可插拔 Skill 为执行后端的小型 Agent 框架」** 建设与写简历。  
> 原则：**先立 Runtime，再挂插件化 / 沙箱 / 自进化**。不再往清单堆应用层功能。

关联文档：[architecture.md](./architecture.md) · [roadmap.md](./roadmap.md) · [features.md](./features.md) · [development.md](./development.md)

**落地状态**：P0–P3 已在 `agent/harness/` 接通 QQ 路径。Run 启动时把当时的 `guardrails.md` 冻进 `guardrail_text`；不可逆技能在 UNKNOWN/FAILED 之后，若文案含「禁止自动重试」，同参数不会再执行。`postconditions.py` 的 `check(result)` 在 L1 里跑，失败会把这次工具记成 FAILED。

---

## 0. 问题重述：缺的不是功能，是承重墙

### 0.1 现有资产的真实归类


| 层          | 现状（已落地）                                                           | 在目标架构中的角色                                                     |
| ---------- | ----------------------------------------------------------------- | ------------------------------------------------------------- |
| 前端接入       | NapCat / OneBot、限流、safe_send、job_queue、Admin / Magic Link         | **IM Adapter**（可替换）                                           |
| 领域能力       | 文件资产、记忆/画像、催办、搜索、Vault、生活助手                                       | **Skill / 工具层**（应自描述、可卸载）                                     |
| 中间 Runtime | `agent/harness/`：Run、intent 账本、契约、沙箱、约束演进 | **Harness Runtime**（QQ 每条消息一次 Run） |


### 0.2 面试追问当前接不住的原因

- 「Agent Loop 怎么设计？」→ 只能答到「拼 prompt → chat → execute_tool」，没有 **Session/Run 生命周期**。
- 「工具失败怎么恢复？」→ 无 **intent 账本**，副作用是否已发生不可判定，无法进入 UNKNOWN / 重放 / 人工接管。
- 「插件热插拔不炸？」→ 现有 `reload_plugin` 只 reload 模块并再次 `register`，无引用计数、无卸载撤销、无版本快照。

### 0.3 目标形状（Thin Harness + Fat Skills）

```text
IM Adapter (QQ/OneBot/…)  ←→  Harness Runtime  ←→  Skill Registry
                                    ↓
                          Sandbox / Effect Adapter
                                    ↓
                          Trace / Eval / Metrics
```

Harness 五大支柱（本计划逐项落地）：

1. **任务边界** —— Session / Run 状态机
2. **上下文管理** —— 压缩、意图门控、按 Run 绑定的 Skill 快照
3. **状态持久化** —— Run 快照 + intent 账本
4. **失败恢复** —— effect_class 语义 + UNKNOWN + 重试/人工
5. **权限体系** —— Skill permissions + 沙箱策略

---

## 1. 与现状的差距（对照代码）


| 能力      | 现状                                                              | 目标缺口                                                             |
| ------- | --------------------------------------------------------------- | ---------------------------------------------------------------- |
| Loop    | QQ 路径由 `run_qq_agent` 包一层 Run；模型循环仍在 `core/loop.py` | 已有 Run 状态机 + 持久化 |
| 工具执行    | `execute_tool` 先写 STARTED，再按沙箱策略执行，postcondition 失败记 FAILED | 已接通账本 |
| 插件      | `plugins/*/manifest.yaml`，注册表按需加载，引用中不可卸 | 已有版本快照与引用计数 |
| 沙箱      | `sandbox_policy` 为 process/ast 时走 L2/L1；越权读和对外连接失败 | 已挂到 Skill 执行链 |
| 可观测     | `/metrics` 含成功率、UNKNOWN 比例、沙箱失败次数；`/harness/runs/{id}` | 已有 Run trace |
| Adapter | QQ channel 与 loop 耦合偏深                                          | Adapter 只投递 `UserEvent`，收回 `OutboundMessage`                     |


**刻意不做（本阶段）**：再加 OCR / Calendar OAuth / 插件市场 / OneBot 全量 asyncio——与承重墙无关。

---

## 2. 目标模块布局（建议落盘）

```text
agent/
  harness/                 # ← 新建：唯一核心
    session.py             # Session（用户/群作用域）
    run.py                 # Run 状态机 + 快照
    intent_ledger.py       # 工具 intent 账本
    effect.py              # EffectClass / UNKNOWN / 确认语义
    skill_contract.py      # SkillManifest 协议
    registry.py            # 注册表、版本快照、引用计数
    executor.py            # Skill 执行链（沙箱路由 + postcondition）
    sandbox/
      base.py
      process_sandbox.py   # L2：subprocess + rlimit + 禁网
      ast_sandbox.py       # L1：既有 AST 思路迁入
    evolve/                # P2：离线自改进
      trace_store.py
      guardrail_miner.py
      behavior_diff.py
      snapshot.py
  adapter/                 # 可选：从 channel 抽出的薄接口
    types.py               # UserEvent / OutboundMessage
  channel/                 # 保留：QQ Adapter 实现
  skills/ 或 plugins/      # 领域 Skill：memory / files / schedule / search / vault
```

迁移策略：先 **并行落地 harness/**，QQ 路径逐步改走 `HarnessRuntime.handle(event)`；旧 `agent_loop` 在过渡期作为内部实现细节，避免大爆炸改写。

---

## 3. 阶段划分与验收

### P0 —— 不做就不叫 Harness（承重墙）

**目标**：任何一次用户消息 = 一次可观测、可中断、可恢复的 **Run**。

#### 3.0.1 Session / Run 状态机

建议状态：

```text
CREATED → PLANNING → TOOL_PENDING → TOOL_RUNNING
       → AWAITING_CONFIRM → UNKNOWN → SUCCEEDED | FAILED | CANCELLED | ABORTED
```

- `Session`：按 `(channel, user_id, group_id)` 隔离；挂短期上下文与活跃 Run 指针。  
- `Run`：绑定 `run_id`、输入事件、消息轨迹、Skill 版本快照 id、当前状态、错误码。  
- 落盘：`agent/.runtime/qq/harness/runs/{run_id}.json`（或 SQLite `runs` 表）。

**验收**：进程重启后，未完成 Run 可从快照恢复到「继续 / 标记失败 / 人工接管」之一；metrics 能列出活跃 Run。

#### 3.0.2 Skill 统一契约（最小字段）

```python
class EffectClass(Enum):
    IDEMPOTENT = "idempotent"           # 可随意重试
    RETRYABLE = "retryable"             # 可重试，需幂等键
    IRREVERSIBLE = "irreversible"       # 不可逆（发消息、删文件）
    REQUIRES_CONFIRM = "requires_confirm"  # 必须用户确认

@dataclass
class SkillManifest:
    name: str
    version: str
    effect_class: EffectClass
    permissions: list[str]
    sandbox_policy: str                 # "none" | "ast" | "process"
    precondition: Callable | None = None
    postcondition: Callable | None = None
    idempotency_key: Callable | None = None
    rollback: Callable | None = None    # 可逆副作用；P1 强化
```

把现有 `tools/qq.py` 里的 handler **包一层 Manifest**（先不拆目录也行）：例如 `send_local_file` → `IRREVERSIBLE`；`web_search` → `IDEMPOTENT`；`delete_file` → `REQUIRES_CONFIRM`（已有删除确认可对齐）。

**验收**：每个 QQ 工具有 `effect_class`；执行前可打印/落盘契约字段；缺契约的 Skill 禁止进入生产路径。

#### 3.0.3 工具 Intent 账本

每条工具调用写入：


| 字段                           | 含义                                               |
| ---------------------------- | ------------------------------------------------ |
| `intent_id`                  | 唯一 id                                            |
| `run_id`                     | 所属 Run                                           |
| `skill` / `version`          | 快照绑定                                             |
| `args_hash`                  | 参数摘要                                             |
| `idempotency_key`            | 可选                                               |
| `status`                     | PLANNED / STARTED / SUCCEEDED / FAILED / UNKNOWN |
| `effect_class`               | 复制自 Manifest                                     |
| `started_at` / `finished_at` | 时间                                               |
| `result_digest`              | 结果摘要（非全文）                                        |


超时、进程崩溃、无返回 → 标记 **UNKNOWN**（尤其 `IRREVERSIBLE`）。

**验收**：人为杀掉工具执行中的进程后，重启能看到 UNKNOWN intent；面试可演示「不确定是否已发消息」的分支处理。

#### 3.0.4 UNKNOWN 恢复策略（写死决策表）


| effect_class     | UNKNOWN 默认策略                 |
| ---------------- | ---------------------------- |
| IDEMPOTENT       | 自动重试（有上限）                    |
| RETRYABLE        | 用同一 idempotency_key 重试；下游需支持 |
| IRREVERSIBLE     | **不自动重试**；提示用户确认「是否已发生」或人工标记 |
| REQUIRES_CONFIRM | 回退到待确认；不重复副作用                |


**验收**：单测覆盖四类决策；QQ 侧 UNKNOWN 有一句口语说明，禁止静默。

#### P0 交付物清单

- [ ] `agent/harness/` 骨架 + Run/Session/Ledger  
- [ ] QQ 工具全部挂 Manifest（可先集中在一张表）  
- [ ] `execute` 路径写账本  
- [ ] 崩溃注入测试 / 冒烟：`python -m agent.smoke_test` 增加 harness 用例  
- [ ] 文档：本文件 P0 勾选 + architecture 更新为「Adapter–Runtime–Skill」  

**简历句（P0 完成后可用）**：  
「以 QQ 为 Adapter 构建 Agent Harness Runtime，统一 Session/Run 状态机、Skill 契约与工具 intent 账本，支持副作用 UNKNOWN 判定与恢复策略。」

---

### P1 —— 简历核心深度（插件化 + 进程沙箱）✅

实现：`agent/harness/registry.py`（只扫 manifest、按需 import、引用计数、版本快照）、插件 `unregister`、`agent/harness/sandbox/`（L1 AST + L2 子进程）。执行链在 `execute_tool` → `executor.dispatch` → intent 账本（含 usage）。

#### 3.1.1 自描述注册表

- 扫描 `plugins/*/manifest.yaml`（或 json 扩展字段），构建能力索引。  
- **按需加载**：Run 需要某 Skill 时再 import；启动只读元数据。  
- **引用计数**：`run_refcounts[skill@version]`；为 0 才允许 unload/upgrade。  
- **版本快照**：Run 创建时冻结 `SkillSnapshot`；执行中途升级不影响该 Run。

#### 3.1.2 可逆卸载（最小可逆插件）

插件必须实现 `unregister(registry)`：撤销 tool、interceptor、定时任务、事件监听、打开的连接。  
`reload` = `unregister` → 加载新版本 → `register`；失败则保持旧版本或标记插件 DISABLED，**不影响已有 Run**。

**验收**：加载 echo → 注册定时器 → unload 后定时器不再触发；加载抛错不影响主进程。

#### 3.1.3 分层沙箱挂到执行链

```text
Skill 调用
  → precondition
  → 查 sandbox_policy
  → none | ast(L1) | process(L2)
  → 捕获 exit_code / stdout / stderr / 资源用量
  → postcondition
  → 写 intent 账本
```

**L2 优先实现**（Windows 上可用作业对象/超时杀进程；Linux 上 `resource.setrlimit` + 禁网）：

- 超时、内存上限、工作目录限制在用户沙箱路径  
- 不可信 / 模型生成脚本强制 L2  
- 可信内置 Skill 可 `none` 或 L1

**验收**：一段「读 `/etc/passwd` 或乱连外网」的脚本在 L2 失败且主进程存活；用量写入 trace。

**简历句**：  
「设计自描述 Skill 注册表（版本快照绑定、引用计数、可逆卸载）；按 effect_class / sandbox_policy 分层路由执行环境，不可信 Skill 进进程隔离，结果纳入 postcondition 与 intent 账本。」

---

### P2 —— 差异化亮点（受控自进化，不做模型自训练）✅

实现：`agent/harness/evolve/`。只允许改 `guardrails.md` / `skill_notes.md` / `postconditions.py`。候选约束先做行为对照（含真实失败 Run），失败丢弃，通过才晋升；`rollback(rev)` 按快照恢复。晋升后的文案在 `begin_intent` 生效，不是只贴进提示词。`check(result)` 在 L1 沙箱里验证工具输出。`EmbodiedSim.grasp` 与不可逆发消息共用 UNKNOWN 询问策略。

### P3 —— 可观测性补强 ✅

`GET /harness/runs` 与 `GET /harness/runs/{run_id}` 返回状态、意图、沙箱用量。metrics 增加 `run_success_rate`、`unknown_rate`、`sandbox_kill_count`。

#### 3.2.1 可编辑组件清单（白名单）

仅允许自修改：

- `guardrails.md` / 系统约束片段  
- 某 Skill 的「使用说明」文本  
- 简单 `postcondition` 检查脚本（在沙箱内跑）

禁止自修改：权限表、effect_class、沙箱实现、Adapter 协议。

#### 3.2.2 离线回路

```text
失败 Run traces（N 条）
  → 约束提炼（LLM 生成候选 guardrails diff）
  → Behavior Diff：同一回放集上旧/新 Harness 各跑一遍
  → 通过才晋升为新 Harness 快照；否则丢弃
  → 任意 Run 可绑定并回滚到历史快照
```

**验收**：人为制造一类可复现失败 → 生成候选修改 → 回放对照失败则不晋升；手动回滚有效。

**简历句**：  
「实现基于失败 trace 的 Harness 约束自动提炼与行为对照验证；自修改经回放集验证后生效，支持按 Run 粒度回滚。」

#### 3.2.3 可选：EmbodiedSkillAdapter（模拟）

用同一 `effect_class` 语义接一个模拟「navigate_to / grasp」后端，演示 **物理副作用与发消息共用恢复策略**。不要求真机器人。

---

### P3 —— 可观测性补强

- Run Trace 面板（Admin 已有则扩展）：状态、intent 列表、UNKNOWN、沙箱用量  
- 与现有 `evals/` 打通：回放集 = Behavior Diff 输入  
- 「你怎么监控 Agent」面试标准答案：metrics 已有 embedding/http/vector，补 **run_success_rate / unknown_rate / sandbox_kill_count**

---

## 4. 建议实施顺序（日历感）


| 周次（参考） | 焦点                           | 产出                 |
| ------ | ---------------------------- | ------------------ |
| W1     | P0 状态机 + 落盘                  | Run 可创建/结束/崩溃可见    |
| W2     | P0 Manifest + 账本 + UNKNOWN 表 | QQ 工具全挂契约；单测       |
| W3     | 切 QQ 主路径走 Runtime            | channel 只当 Adapter |
| W4–W5  | P1 注册表 + 可逆卸载                | 热加载故事可演示           |
| W5–W6  | P1 L2 沙箱                     | 恶意脚本演示             |
| W7+    | P2 离线自改进 MVP                 | 一次回滚故事             |
| 穿插     | P3 Trace                     | Admin / metrics    |


若时间只够两周：**只做 W1–W3（纯 P0）**，简历深度已够；插件市场、OCR、asyncio 重写继续后置。

---

## 5. 简历与面试：把清单翻译成架构决策

### 5.1 改写对照


| 改写前                           | 改写后                                                                               |
| ----------------------------- | --------------------------------------------------------------------------------- |
| 实现 QQ 机器人，支持文件、记忆、催办、搜索、Vault | 以 QQ 为 Adapter 构建 Agent Harness Runtime，统一会话隔离、Skill 调度与副作用恢复；文件/记忆/催办等为可插拔 Skill |
| 插件热加载                         | 自描述 Skill 注册表：运行时发现、版本快照绑定、引用计数与可逆卸载                                              |
| Python DSL + AST 隔离           | 按 effect_class / sandbox_policy 分层执行；不可信 Skill 进进程隔离，结果进 postcondition 与账本        |
| 记忆 / 知识卡片                     | Run 级持久化与上下文管理；支持中断恢复与状态快照（记忆 Skill 为其上应用）                                        |
| 自进化                           | 失败 trace → 约束提炼 → 行为对照 → 快照晋升/回滚（非模型自训练）                                          |


### 5.2 三个深度锚点（必须能演）

1. **工具超时/崩溃的 Run**：如何进 UNKNOWN、为何不自动重试发消息、如何人工确认。
2. **一次插件热加载**：加载了什么、失败如何隔离、卸载撤销了什么定时器/监听。
3. **一次自修改被回滚**：改了哪条 guardrail、Behavior Diff 指标、为何判定失败、回滚粒度。

### 5.3 诚实边界（写进简历脚注）

- QQ 仍是当前唯一生产 Adapter；多前端是架构预留。  
- L3/L4 沙箱（seccomp / Firecracker）讲清取舍即可，不必实现。  
- 自进化是 **离线受控回路**，不是在线自主改权重。

---

## 6. 明确不做什么（防功能回流）


| 诱惑                          | 为什么不做                       |
| --------------------------- | --------------------------- |
| 再堆生活助手话术 / 新仪表盘卡片           | 不增加 Runtime 深度              |
| 插件市场 + 远程热更新                | 依赖 P1 契约与沙箱，否则是攻击面          |
| OneBot 全量 asyncio           | 运维优化，非 Harness 叙事           |
| Google Calendar OAuth / OCR | 领域 Skill，P0/P1 完成后再说        |
| 「Multi-Agent / LangGraph」口号 | 未实现勿写；本项目卖点是自研 Thin Harness |


---

## 7. 验收总表（Definition of Done）


| 级别  | DoD                                                   |
| --- | ----------------------------------------------------- |
| P0  | 任意 QQ 消息有 `run_id`；工具有账本；四类 UNKNOWN 策略有测；崩溃可观察        |
| P1  | 插件可卸载且无泄漏；同名多版本按 Run 快照绑定；L2 跑通拒网/超时                  |
| P2  | 至少一次「提炼 → 对照失败 → 丢弃」与一次「对照通过 → 晋升 → 可回滚」记录            |
| P3  | Admin 或 CLI 能按 run_id 查看 trace；unknown_rate 进 metrics |


---

## 8. 下一步（开工指令）

1. 建 `agent/harness/` 包与空实现 + 单测骨架。
2. 为 `tools/qq.py` 导出 `SKILL_MANIFESTS` 表（不改行为，只加元数据）。
3. 在 `channel/run.py`（或等价入口）包一层 `HarnessRuntime.start_run(...)`。
4. 每完成一档，勾选本文清单并改 [roadmap.md](./roadmap.md) Phase 6 状态。

---

*文档版本：2026-10-26 · 与「Thin Harness, Fat Skills」及 BoundRun 侧思路对齐；实现以本文件为唯一优先级来源。*