from ..hooks import trigger_hook


def execute_tool(name: str, args: dict, handlers: dict) -> str:
    """封装执行工具的预处理、执行、后处理流程。"""
    blocked = trigger_hook("PreToolUse", name, args)
    if blocked:
        return str(blocked)

    handler = handlers.get(name)
    try:
        output = handler(**args)
    except Exception as e:
        return f"Error: 工具{name}执行失败\n错误信息: {str(e)}"

    trigger_hook("PostToolUse", name, output)
    return str(output)
