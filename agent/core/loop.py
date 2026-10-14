"""父 Agent 集成循环（迷你 harness）：多种机制挂在同一个 while True 上。

每轮固定顺序（不含 cron / teams / worktree）：

    inject_background_results   # 后台 bash → <task_notification>
    _update_system_message      # 记忆召回 + skills/任务约定 + MCP 状态
                                # （频道模式可用 system_provider 覆盖）
    COMPACTOR.prepare           # 上下文预算
    assemble_tool_pool / 注入工具
    chat                        # LLM；溢出则 reactive compact
    无 tool_calls → Stop + 记忆提取/整合 → return
    有 tool_calls → execute_tool → 追加结果

QQ / 其它频道：传入 tools+handlers+system_provider，共用本循环与 llm/hooks/压缩。
"""

from __future__ import annotations

import json
from collections.abc import Callable

import requests

from ..background import inject_background_results
from ..compaction import COMPACTOR, MAX_REACTIVE_RETRIES, is_context_overflow
from ..core.execute import execute_tool
from ..core.llm import chat
from ..hooks import trigger_hook
from ..mcp import assemble_tool_pool, mcp_system_addon
from ..memory import build_system, consolidate_memories, extract_memories, load_memories
from ..tools import TASK_TOOLS, TOOL_HANDLERS


def _update_system_message(
    messages: list,
    system_provider: Callable[[list], str] | None = None,
    *,
    use_mcp: bool = True,
) -> None:
    """组装本轮 system。"""
    if system_provider is not None:
        system = system_provider(messages)
    else:
        system = build_system(load_memories(messages))
        if use_mcp:
            addon = mcp_system_addon()
            if addon:
                system = f"{system}\n\n{addon}"
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system
    else:
        messages.insert(0, {"role": "system", "content": system})


def agent_loop(
    messages: list,
    active_request: str = "",
    *,
    tools: list | None = None,
    handlers: dict | None = None,
    system_provider: Callable[[list], str] | None = None,
    use_mcp: bool = True,
    extract_memory: bool = True,
    todo_reminder: bool = True,
    max_rounds: int | None = None,
) -> str | None:
    """唯一主循环：注入 → 拼 prompt → 压缩 → 调模型 → 工具 → 回灌。

    返回最后一条 assistant 文本（无工具收尾时）；频道侧可直接当回复。
    终端 Coding Agent 仍可忽略返回值。

    频道模式（如 QQ）示例：
        agent_loop(messages, text, tools=..., handlers=..., system_provider=...,
                   use_mcp=False, extract_memory=False, todo_reminder=False, max_rounds=6)
    """
    rounds_since_todo = 0
    reactive_retries = 0
    rounds = 0
    last_text: str | None = None

    while True:
        if max_rounds is not None and rounds >= max_rounds:
            return last_text or "处理轮次过多，请把问题拆短一点再试。"
        rounds += 1

        # 1) 后台任务完成通知
        inject_background_results(messages)
        # 2) system
        _update_system_message(messages, system_provider, use_mcp=use_mcp)
        # 3) 上下文压缩
        messages[:] = COMPACTOR.prepare(messages, active_request)
        # 4) 工具池：显式注入（频道）或 Coding 默认 + MCP
        if tools is not None and handlers is not None:
            pool_tools, pool_handlers = tools, handlers
            if use_mcp:
                pool_tools, pool_handlers = assemble_tool_pool(tools, handlers)
        else:
            pool_tools, pool_handlers = assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)

        # 5) 调模型
        try:
            msg = chat(messages, tools=pool_tools, max_tokens=5000)
        except requests.HTTPError as e:
            if reactive_retries < MAX_REACTIVE_RETRIES and is_context_overflow(e):
                print("\033[33m[reactive compact] 上下文仍然过长，应急压缩后重试\033[0m")
                messages[:] = COMPACTOR.reactive_compact(messages, active_request)
                reactive_retries += 1
                continue
            raise

        messages.append(msg)
        if msg.get("content"):
            last_text = str(msg["content"]).strip()

        # 6a) 无工具 → 收尾
        if not msg.get("tool_calls"):
            trigger_hook("Stop", messages)
            if extract_memory and extract_memories(messages):
                consolidate_memories()
            return last_text or None

        # 6b) 执行工具
        tool_results = []
        used_planning = False
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")
            output = execute_tool(
                name,
                args,
                pool_handlers,
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

        if todo_reminder:
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
