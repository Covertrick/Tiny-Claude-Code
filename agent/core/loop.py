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
    """按当前对话召回记忆，并追加已连接 MCP 说明。"""
    system = build_system(load_memories(messages))
    addon = mcp_system_addon()
    if addon:
        system = f"{system}\n\n{addon}"
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system
    else:
        messages.insert(0, {"role": "system", "content": system})


def agent_loop(messages: list, active_request: str = ""):
    """父 Agent 主循环：记忆 → 后台结果 → 动态工具池 → 调模型 → 执行工具。"""
    rounds_since_todo = 0
    reactive_retries = 0

    while True:
        inject_background_results(messages)
        # 每轮刷新 system（含记忆召回 + 已连接 MCP）；connect_mcp 后下一轮生效
        _update_system_message(messages)
        messages[:] = COMPACTOR.prepare(messages, active_request)

        tools, handlers = assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)

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

        if not msg.get("tool_calls"):
            trigger_hook("Stop", messages)
            if extract_memories(messages):
                consolidate_memories()
            return None

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
