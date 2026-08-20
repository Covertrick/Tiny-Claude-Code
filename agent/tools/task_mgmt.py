"""持久化任务工具入口：把 agent.tasks API 包装成返回 str 的 handler。"""

from agent.tasks import (
    claim_task,
    complete_task,
    create_task,
    get_task,
    list_tasks,
    update_task,
)


def run_create_task(subject: str, description: str = "") -> str:
    """创建任务；返回含运行时 id 的说明。失败时返回 Error 字符串。"""
    try:
        task = create_task(subject, description)
    except Exception as error:
        return f"Error: {error}"
    print(f"  [create] {task.subject}")
    return f"已创建 {task.id}: {task.subject}"


def run_update_task(task_id: str, addBlockedBy: list[str]) -> str:
    """为任务追加 blockedBy（参数名与工具 schema 对齐）。失败返回 Error。"""
    try:
        task = update_task(task_id, addBlockedBy)
    except Exception as error:
        return f"Error: {error}"
    dependencies = ", ".join(task.blockedBy) or "(无)"
    print(f"  [update] {task.subject} blockedBy: {dependencies}")
    return f"已更新 {task.id} blockedBy: {dependencies}"


def run_list_tasks() -> str:
    """列出全部任务：状态标记、id、标题、owner、依赖。"""
    try:
        tasks = list_tasks()
    except Exception as error:
        return f"Error: {error}"
    if not tasks:
        return "暂无任务。请先用 create_task 创建。"
    lines = []
    for task in tasks:
        marker = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
        }.get(task.status, "[?]")
        dependencies = (
            f" (blockedBy: {', '.join(task.blockedBy)})" if task.blockedBy else ""
        )
        owner = f" [{task.owner}]" if task.owner else ""
        lines.append(
            f"{marker} {task.id}: {task.subject} "
            f"[{task.status}]{owner}{dependencies}"
        )
    return "\n".join(lines)


def run_get_task(task_id: str) -> str:
    """按 id 返回任务 JSON 文本。失败返回 Error。"""
    try:
        return get_task(task_id)
    except Exception as error:
        return f"Error: {error}"


def run_claim_task(task_id: str) -> str:
    """以 agent 身份认领任务（依赖未齐时返回说明字符串）。"""
    try:
        return claim_task(task_id, owner="agent")
    except Exception as error:
        return f"Error: {error}"


def run_complete_task(task_id: str) -> str:
    """以 agent 身份完成已认领任务；可能附带新解锁的下游标题。"""
    try:
        return complete_task(task_id, owner="agent")
    except Exception as error:
        return f"Error: {error}"
