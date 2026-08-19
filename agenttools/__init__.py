"""父 Agent 工具表：BASE_TOOLS 加上 task / todo_write / load_skill。"""

from .base import BASE_HANDLERS, BASE_TOOLS
from .skill import load_skill
from .task import run_subagent
from .todo import run_todo_write

TASK_TOOLS = [
    *BASE_TOOLS,
    {
        "type": "function",
        "function": {
            "name": "task",
            "description": "执行子Agent任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要执行的任务内容"}
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "创建并管理当前会话的任务列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "maxItems": 20,
                        "description": "任务列表，每次传入完整列表（覆盖更新）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": "任务内容",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "任务状态",
                                },
                            },
                            "required": ["content", "status"],
                        },
                    }
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "加载技能",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "要加载的技能名称"}
                },
                "required": ["name"],
            },
        },
    },
]

TOOL_HANDLERS = {
    **BASE_HANDLERS,
    "task": run_subagent,
    "todo_write": run_todo_write,
    "load_skill": load_skill,
}

__all__ = ["TASK_TOOLS", "TOOL_HANDLERS"]
