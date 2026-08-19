from ..hooks import trigger_hook


def execute_tool(name: str, args: dict, handlers: dict) -> str:
    """执行一次工具：PreToolUse → handler → PostToolUse。

    PreToolUse 若返回非 None，视为拦截，直接把该结果当输出，不调用 handler。
    """
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
