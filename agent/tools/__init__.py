"""父 Agent 工具表：BASE_TOOLS + task / todo_write / load_skill + 持久化任务工具。"""

from .base import BASE_HANDLERS, BASE_TOOLS
from .skill import load_skill
from .task import run_subagent
from .task_mgmt import (
    run_claim_task,
    run_complete_task,
    run_create_task,
    run_get_task,
    run_list_tasks,
    run_update_task,
)
from .todo import run_todo_write

_TASK_ID_PROP = {
    "type": "string",
    "description": "任务 ID，形如 task_a1b2c3d4（create_task 返回）",
    "pattern": r"^task_[0-9a-f]{8}$",
}

TASK_MGMT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "创建持久化任务节点，返回运行时生成的 task_xxxxxxxx ID。有依赖图时先全部 create，再用 update_task 连边。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "任务标题（短名称）",
                    },
                    "description": {
                        "type": "string",
                        "description": "可选的详细说明",
                    },
                },
                "required": ["subject"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "给任务追加 blockedBy 依赖；必须使用 create_task 返回的精确 ID。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": _TASK_ID_PROP,
                    "addBlockedBy": {
                        "type": "array",
                        "minItems": 1,
                        "items": _TASK_ID_PROP,
                        "description": "前置任务 ID 列表（这些完成后当前任务才能 claim）",
                    },
                },
                "required": ["task_id", "addBlockedBy"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "列出全部持久化任务：状态、owner、依赖。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_task",
            "description": "按 ID 获取单条任务的 JSON 详情。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": _TASK_ID_PROP,
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "claim_task",
            "description": "认领依赖已完成的 pending 任务，变为 in_progress。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": _TASK_ID_PROP,
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "完成当前 agent 已认领的 in_progress 任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": _TASK_ID_PROP,
                },
                "required": ["task_id"],
            },
        },
    },
]

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
            "description": "创建并管理当前会话的任务列表（内存，无跨会话依赖图）",
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
    *TASK_MGMT_TOOLS,
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
    "create_task": run_create_task,
    "update_task": run_update_task,
    "list_tasks": run_list_tasks,
    "get_task": run_get_task,
    "claim_task": run_claim_task,
    "complete_task": run_complete_task,
    "load_skill": load_skill,
}

__all__ = ["TASK_TOOLS", "TOOL_HANDLERS", "TASK_MGMT_TOOLS"]
