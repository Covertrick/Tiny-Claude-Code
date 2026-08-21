"""后台 bash：线程执行命令，主循环稍后 collect / inject 结果。"""

from __future__ import annotations

import threading


class BackgroundManager:
    """管理显式标记为后台的 bash 任务。"""

    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.results: dict[str, str] = {}
        self._ready: list[str] = []
        self._counter = 0
        self._lock = threading.Lock()

    def start(self, name: str, args: dict, tool_call_id: str) -> str:
        """启动后台 bash；返回 bg_xxxx。"""
        if name != "bash":
            raise ValueError(f"不支持的后台任务: {name}")
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command 必须是非空字符串")

        with self._lock:
            self._counter += 1
            task_id = f"bg_{self._counter:04d}"
            self.tasks[task_id] = {
                "tool_call_id": tool_call_id,
                "command": command,
                "status": "running",
            }

        thread = threading.Thread(
            target=self._run,
            args=(task_id, command),
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            with self._lock:
                self.tasks.pop(task_id, None)
            raise
        print(f"  [background] started {task_id}: {command[:60]}")
        return task_id

    def _run(self, task_id: str, command: str) -> None:
        """在工作线程里跑 bash（延迟导入，避免循环依赖）。"""
        from ..tools.base import format_bash_result, run_bash_process

        try:
            output, exit_code = run_bash_process(command)
            result = format_bash_result(output, exit_code)
            status = "completed" if exit_code == 0 else "failed"
        except Exception as error:
            result = f"Error: 后台任务失败\n错误信息: {error}"
            status = "failed"

        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            task["status"] = status
            self.results[task_id] = result
            self._ready.append(task_id)

    def collect(self) -> list[str]:
        """取出已完成任务，返回 <task_notification> 文本列表。"""
        with self._lock:
            ready = []
            for task_id in self._ready:
                task = self.tasks.pop(task_id, None)
                result = self.results.pop(task_id, "")
                # 必须是 is not None：写反会导致永远收不到结果
                if task is not None:
                    ready.append((task_id, task, result or ""))
            self._ready.clear()

        notifications = []
        for task_id, task, result in ready:
            notifications.append(
                "<task_notification>\n"
                f"  <task_id>{task_id}</task_id>\n"
                f"  <status>{task['status']}</status>\n"
                f"  <command>{task['command']}</command>\n"
                f"  <summary>{result[:500]}</summary>\n"
                "</task_notification>"
            )
            print(f"  [background] collected {task_id}: {task['status']}")
        return notifications


BACKGROUND = BackgroundManager()


def should_run_background(name: str, args: dict) -> bool:
    """是否将本次工具调用丢到后台线程。"""
    return name == "bash" and args.get("run_in_background") is True


def inject_background_results(messages: list) -> int:
    """把已完成的后台结果注入 messages，返回注入条数。"""
    notifications = BACKGROUND.collect()
    if not notifications:
        return 0
    text = "\n\n".join(notifications)
    if messages and messages[-1].get("role") == "user":
        content = messages[-1].get("content", "")
        if isinstance(content, str):
            messages[-1]["content"] = f"{content}\n\n{text}" if content else text
        else:
            messages.append({"role": "user", "content": text})
    else:
        messages.append({"role": "user", "content": text})
    return len(notifications)
