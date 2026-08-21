"""评测预算规划（qwen3.7-plus，剩余额度约 47 万 token）。

原则
----
1. 能离线验的不调 API（B/C/D/E 的核心逻辑）→ 0 token
2. 在线题精简覆盖 6 类，单次全跑目标 ≤ 15 万 token
3. 预留 ≥ 20 万给调试复跑 / 失败重试
4. F（长上下文）最贵，默认只跑 2 题，且可用 --skip-f

预算表（估算，按「成功一次」）
----------------------------
| 模式 | 类别 | 题量 | 估 token/题 | 小计 |
|------|------|------|-------------|------|
| offline | B+C+D+E harness | ~25 | 0 | 0 |
| online | A 工具 | 12 | ~2.5k | ~30k |
| online | B 权限（少量端到端） | 3 | ~2k | ~6k |
| online | C 任务图 | 6 | ~4k | ~24k |
| online | D 后台 | 4 | ~3k | ~12k |
| online | E MCP | 4 | ~3k | ~12k |
| online | F 上下文 | 2 | ~15–25k | ~40k |
| **合计 online** | | **31** | | **~124k** |
| 失败重试余量 | | | | ~50k |
| **建议占用** | | | | **~18 万** |
| 剩余额度缓冲 | | | | **~29 万** |

推荐命令
--------
# 先零成本验 harness
python -m evals.runner --mode offline

# 省额度：跳过 F，跑 A–E
python -m evals.runner --mode online --skip-f --token-budget 120000

# 全量（含 2 道 F）
python -m evals.runner --mode online --token-budget 180000
"""

BUDGET = {
    "remaining_tokens_hint": 470_000,
    "target_online_tokens": 124_000,
    "retry_reserve": 50_000,
    "hard_cap_default": 180_000,
    "keep_buffer": 240_000,
    "categories": {
        "A": {"online": 12, "est_per": 2500},
        "B": {"online": 3, "offline": 10, "est_per": 2000},
        "C": {"online": 6, "offline": 8, "est_per": 4000},
        "D": {"online": 4, "offline": 4, "est_per": 3000},
        "E": {"online": 4, "offline": 4, "est_per": 3000},
        "F": {"online": 2, "est_per": 20000},
    },
}
