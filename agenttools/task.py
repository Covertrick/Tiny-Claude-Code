from typing import Any
import json

from ..core.execute import execute_tool
from ..core.llm import chat
from ..hooks import trigger_hook
from ..skill_load.loader import SUB_SYSTEM_PROMPT
from .base import BASE_HANDLERS, BASE_TOOLS

SUB_TOOLS = list(BASE_TOOLS)
SUB_HANDLERS = dict(BASE_HANDLERS)


def extract_text(content: Any) -> str:
    """从 assistant 的 content 提取最终文本（给父 Agent 的 tool_result）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def run_subagent(content: str) -> str:
    """执行子Agent，返回最终文本"""
    print("\n\033[35m[SubAgent] 开始执行任务\033[0m")
    messages = [
        {"role": "system", "content": SUB_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    for _ in range(30):
        msg = chat(messages, tools=SUB_TOOLS, max_tokens=5000)
        messages.append(msg)

        if not msg.get("tool_calls"):
            trigger_hook("Stop", messages)
            print(f"\n\033[35m[SubAgent] 任务执行完成\033[0m")
            return extract_text(msg.get("content", ""))

        tool_results = []
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")
            output = execute_tool(name, args, SUB_HANDLERS)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output,
            })
        messages.extend(tool_results)
    print(f"\n\033[35m[SubAgent] 任务执行完成\033[0m")
    return "Sub Agent 执行30轮后，没有返回结果"
