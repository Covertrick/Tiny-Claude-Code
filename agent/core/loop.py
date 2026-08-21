"""父 Agent 集成循环（迷你 harness）：多种机制挂在同一个 while True 上。

每轮固定顺序（不含 cron / teams / worktree）：

    inject_background_results   # 后台 bash → <task_notification>
    _update_system_message      # 记忆召回 + skills/任务约定 + MCP 状态
    COMPACTOR.prepare           # 上下文预算
    assemble_tool_pool          # 内置工具 + 已连接 mcp__*
    chat                        # LLM；溢出则 reactive compact
    无 tool_calls → Stop + 记忆提取/整合 → return
    有 tool_calls → execute_tool（PreToolUse / 后台分发 / MCP）→ 追加结果
"""

import json

import requests

from ..background import inject_background_results
from ..compaction import COMPACTOR, MAX_REACTIVE_RETRIES, is_context_overflow
from ..core.execute import execute_tool
from ..core.llm import chat
from ..hooks import trigger_hook
from ..mcp import assemble_tool_pool, mcp_system_addon
from ..memory import build_system, consolidate_memories, extract_memories, load_memories
from ..tools import TASK_TOOLS, TOOL_HANDLERS


def _update_system_message(messages: list) -> None:
    """组装本轮 system：记忆 + 基础约定 + 已连接 MCP。"""
    system = build_system(load_memories(messages))
    addon = mcp_system_addon()
    if addon:
        system = f"{system}\n\n{addon}"
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system
    else:
        messages.insert(0, {"role": "system", "content": system})


def agent_loop(messages: list, active_request: str = ""):
    """唯一主循环：注入 → 拼 prompt → 压缩 → 调模型 → 工具 → 回灌。"""
    rounds_since_todo = 0
    reactive_retries = 0

    while True:
        # 1) 后台任务完成通知
        inject_background_results(messages)
        # 2) 记忆 / 技能约定 / MCP 状态 → system
        _update_system_message(messages)
        # 3) 上下文压缩管线
        messages[:] = COMPACTOR.prepare(messages, active_request)
        # 4) 动态工具池（connect_mcp 后下一轮出现 mcp__*）
        tools, handlers = assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)

        # 5) 调模型；prompt 过长则应急压缩后重试
        try:
            msg = chat(messages, tools=tools, max_tokens=5000)
        except requests.HTTPError as e:
            if reactive_retries < MAX_REACTIVE_RETRIES and is_context_overflow(e):
                print("\033[33m[reactive compact] 上下文仍然过长，应急压缩后重试\033[0m")
                messages[:] = COMPACTOR.reactive_compact(messages, active_request)
                reactive_retries += 1
                continue
            raise

        messages.append(msg)

        # 6a) 本轮无工具 → Stop hooks + 记忆落盘
        if not msg.get("tool_calls"):
            trigger_hook("Stop", messages)
            if extract_memories(messages):
                consolidate_memories()
            return None

        # 6b) 执行工具（PreToolUse / 后台 bash / MCP 均在 execute_tool）
        tool_results = []
        used_planning = False
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")
            output = execute_tool(
                name,
                args,
                handlers,
                tool_call_id=tool_call.get("id", ""),
            )
            if name in (
                "todo_write",
                "create_task",
                "update_task",
                "claim_task",
                "complete_task",
            ):
                used_planning = True
            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output,
            })

        messages.extend(tool_results)
        rounds_since_todo = 0 if used_planning else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            messages.append({
                "role": "user",
                "content": (
                    "<reminder>请用 todo_write 或 "
                    "create_task/claim_task/complete_task 更新任务进度。</reminder>"
                ),
            })
            rounds_since_todo = 0
            print("\033[33m[reminder] 已提醒模型更新任务进度\033[0m")
