from ..hooks import trigger_hook
from ..background import BACKGROUND, should_run_background

def execute_tool(
    name: str,
    args: dict,
    handlers: dict,
    tool_call_id: str = "",
) -> str:
    """执行一次工具：PreToolUse → handler（或后台 bash）→ PostToolUse。
    PreToolUse 若返回非 None，视为拦截，直接把该结果当输出，不调用 handler。
    bash 且 run_in_background=true 时启动后台线程并返回占位说明。
    """
    blocked = trigger_hook("PreToolUse", name, args)
    if blocked:
        return str(blocked)

    try:
        if should_run_background(name, args):
            task_id = BACKGROUND.start(name, args, tool_call_id or "unknown")
            output = (
                f"[后台任务 {task_id} 已启动] "
                "结果将在后续轮次以 task_notification 注入。"
            )
        else:
            handler = handlers.get(name)
            if handler is None:
                output = f"Error: Unknown tool: {name}"
            else:
                call_args = dict(args)
                call_args.pop("run_in_background", None)
                output = handler(**call_args)
    except Exception as e:
        output = f"Error: 工具{name}执行失败\n错误信息: {str(e)}"
    trigger_hook("PostToolUse", name, output)
    return str(output)