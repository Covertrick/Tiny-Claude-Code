# 评测集（Evals）

面向 Tiny-Claude-Code 的量化评测：覆盖 A–F 六类维度。  
模型：`.env` 中的 `MODEL_NAME`（当前预期 `qwen3.7-plus`）。

## Token 预算（约剩 47 万）

| 项 | Token |
|----|------:|
| 离线 harness（B/C/D/E 核心） | **0** |
| 在线全套（含 2 道 F）一次成功 | ~12.4 万 |
| 失败重试预留 | ~5 万 |
| **建议本轮占用** | **≤ 18 万** |
| 留给日常开发 | ~29 万 |

详见 `budget.py`。

## 快速开始

在项目根目录：

```powershell
# 1) 必跑：零成本验 harness
C:\Miniconda\envs\langchain1.2\python.exe -m evals.runner --mode offline

# 2) 省额度：在线 A–E，跳过 F
C:\Miniconda\envs\langchain1.2\python.exe -m evals.runner --mode online --skip-f --token-budget 120000

# 3) 有余量再跑 F / 全量
C:\Miniconda\envs\langchain1.2\python.exe -m evals.runner --mode online --token-budget 180000
```

只跑某类 / 某题：

```powershell
python -m evals.runner --mode online --categories A,E --token-budget 50000
python -m evals.runner --mode online --ids A01,E05 --token-budget 20000
```

报告输出：`evals/reports/report_*.md` + `.json`

## 题目规模

| 类 | 离线 | 在线 | 说明 |
|----|------|------|------|
| A 工具 | 0 | 12 | 文件/bash 正确性 |
| B 权限 | 7 | 3 | 离线测 hook；在线少量端到端 |
| C 任务图 | 4 | 6 | 离线状态机；在线工具链 |
| D 后台 | 2 | 4 | 占位 + notification |
| E MCP | 4 | 4 | 连接与动态工具 |
| F 上下文 | 0 | 2 | 最贵，默认可 `--skip-f` |

## 主指标

- **Success Rate**：分维度 / 总体通过率  
- **Policy Compliance**：权限与 MCP confirm（离线 B 为主）  
- **Notification Delivery**：后台 D  
- **Tokens / task、Turns（llm_calls）、耗时**：在线报告里的 usage
