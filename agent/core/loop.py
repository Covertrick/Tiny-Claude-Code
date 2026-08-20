import json

import requests

from ..compaction import COMPACTOR, MAX_REACTIVE_RETRIES, is_context_overflow
from ..core.execute import execute_tool
from ..core.llm import chat
from ..hooks import trigger_hook
from ..memory import build_system, consolidate_memories, extract_memories, load_memories
from ..tools import TASK_TOOLS, TOOL_HANDLERS


def _update_system_message(messages: list) -> None:
    """按当前对话召回记忆，刷新 messages 首条 system。"""
    system = build_system(load_memories(messages))
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system
    else:
        messages.insert(0, {"role": "system", "content": system})


def agent_loop(messages: list, active_request: str = ""):
    """父 Agent 主循环：召回记忆 → 压缩 → 调模型 → 执行工具，直到模型不再 tool_calls。

    messages 就地修改。每轮开始时按对话召回记忆并更新 system；
    正常结束时尝试 extract_memories，若有新记忆则触发 consolidate_memories。
    """
    _update_system_message(messages)
    rounds_since_todo = 0
    reactive_retries = 0

    while True:
        messages[:] = COMPACTOR.prepare(messages, active_request)

        try:
            msg = chat(messages, tools=TASK_TOOLS, max_tokens=5000)
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
            output = execute_tool(name, args, TOOL_HANDLERS)
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
