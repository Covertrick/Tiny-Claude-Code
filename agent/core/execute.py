"""工具执行：PreToolUse →（若处于 Harness Run）写 intent 账本 → handler → 收口。

QQ 生产路径要求 Skill 契约。缺契约直接拒绝，不调用 handler。
执行前把意图刷成 STARTED；超时标 UNKNOWN，普通异常标 FAILED。
"""

from __future__ import annotations

from ..background import BACKGROUND, should_run_background
from ..hooks import trigger_hook
from agent.harness.effect import IntentStatus
from agent.harness.runtime import current_run, get_runtime
from agent.harness.store import IntentRecord


def execute_tool(
    name: str,
    args: dict,
    handlers: dict,
    tool_call_id: str = "",
) -> str:
    blocked = trigger_hook("PreToolUse", name, args)
    if blocked:
        return str(blocked)

    run = current_run()
    runtime = get_runtime() if run is not None else None
    intent: IntentRecord | None = None
    if run is not None and runtime is not None:
        got = runtime.begin_intent(run, name, args or {})
        if isinstance(got, str):
            return got
        intent = got

    snap = {}
    if run is not None:
        snap = dict((run.skill_snapshot or {}).get(name) or {})
    usage: dict = {}
    try:
        if should_run_background(name, args):
            task_id = BACKGROUND.start(name, args, tool_call_id or "unknown")
            output = (
                f"[后台任务 {task_id} 已启动] "
                "结果将在后续轮次以 task_notification 注入。"
            )
        else:
            handler = handlers.get(name)
            if handler is None and snap.get("source") == "plugin":
                from agent.harness.registry import get_skill_registry

                handler = get_skill_registry().handler(name, snap.get("version"))
            from agent.harness.executor import dispatch

            output, usage = dispatch(name, dict(args or {}), handler, snap)
    except TimeoutError as e:
        if intent is not None and runtime is not None and run is not None:
            note =                     runtime.complete_intent(
                        run,
                        intent,
                        status=IntentStatus.UNKNOWN,
                        error=str(e),
                        usage=usage,
                    )
            return note or f"Error: 工具{name}超时，结果未知"
        return f"Error: 工具{name}超时\n错误信息: {e}"
    except Exception as e:
        output = f"Error: 工具{name}执行失败\n错误信息: {e}"
        if intent is not None and runtime is not None and run is not None:
            runtime.complete_intent(
                run,
                intent,
                status=IntentStatus.FAILED,
                error=str(e),
                usage=usage,
            )
        trigger_hook("PostToolUse", name, output)
        return str(output)

    if intent is not None and runtime is not None and run is not None:
        text = str(output)
        # handler 自己声明不确定时，升级为 UNKNOWN（不可逆默认不自动重做）
        if text.startswith("UNKNOWN:"):
            note = runtime.complete_intent(
                run,
                intent,
                status=IntentStatus.UNKNOWN,
                result=text,
                usage=usage,
            )
            trigger_hook("PostToolUse", name, note or text)
            return note or text
        failed = text.startswith(("Error:", "沙箱拒绝", "precondition", "postcondition"))
        runtime.complete_intent(
            run,
            intent,
            status=IntentStatus.FAILED if failed else IntentStatus.SUCCEEDED,
            result=text,
            error=text if failed else "",
            usage=usage,
        )
    trigger_hook("PostToolUse", name, output)
    return str(output)
