import json

import requests

from ..compaction import COMPACTOR, MAX_REACTIVE_RETRIES, is_context_overflow
from ..core.execute import execute_tool
from ..core.llm import chat
from ..hooks import trigger_hook
from ..tools import TASK_TOOLS, TOOL_HANDLERS


def agent_loop(messages: list, active_request: str = ""):
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
            return None

        tool_results = []
        used_todo = False
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")
            output = execute_tool(name, args, TOOL_HANDLERS)
            if name == "todo_write":
                used_todo = True
            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output,
            })

        messages.extend(tool_results)
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            messages.append({
                "role": "user",
                "content": "<reminder>请用 todo_write 更新你的任务列表。</reminder>",
            })
            rounds_since_todo = 0
            print("\033[33m[reminder] 已提醒模型更新 todos\033[0m")
