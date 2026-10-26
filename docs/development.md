# 开发说明

## 优先级

1. 读 [harness-runtime-plan.md](./harness-runtime-plan.md)，按 **P0 → P1 → P2 → P3** 推进。  
2. 应用层新功能（OCR、日历 OAuth、插件市场等）默认 **拒绝合入**，除非直接服务 Runtime。  
3. 目录边界见 [architecture.md](./architecture.md)。

## 目录与边界（过渡期）

| 目录 | 职责 | 禁止 |
|------|------|------|
| `channel/` | QQ Adapter：听/说、缓存、拦截、限流 | 直接定义工具副作用语义 |
| `core/` | 现有 `agent_loop`（迁入 `harness/` 前的实现） | 感知 OneBot 协议字段 |
| `harness/` | **目标核心**：Run/账本/契约/沙箱（建设中） | 依赖 QQ API |
| `tools/qq.py` / `plugins/` | Skill 实现与注册 | 绕过账本直接发不可逆副作用 |
| `knowledge/` `files/` `vault/` … | 领域 Skill 实现 | 跨用户读写 |

## 运行

```bash
pip install -r requirements.txt
# agent/.env 至少 API_KEY
python -m agent.smoke_test
python -m agent                 # QQ Adapter + NapCat 引导
```

## 简历表述（随 Phase 6 升级）

**现在可诚实写（Phase 1–5）**：

- 自研 Agent Loop；QQ Adapter 与 Coding CLI 共用循环、工具面隔离  
- 多租户记忆、催办、文件资产、Vault、连接池与向量索引  

**对外主句**：

> 以 QQ 为 Adapter 构建 Agent Harness：Run 状态机、Skill 契约与 intent 账本、版本快照绑定的可逆插件、按策略路由的进程沙箱，以及经回放对照才生效、可按 Run 回滚的约束。

**避免写**：未实现的 Multi-Agent / LangGraph / Firecracker / 在线自训练 / 7×24（除非已部署守护）。

面试三个锚点见 harness 计划 §5.2。
