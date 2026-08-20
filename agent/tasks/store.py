"""持久化任务存储：每个任务一个 JSON 文件，支持依赖图、认领与完成。"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from agent.config import RUNTIME_DIR, TASKS_DIR

TASK_ID_PATTERN = re.compile(r"^task_[0-9a-f]{8}$")


@dataclass
class Task:
    """一条可落盘的任务记录。

    status: pending → in_progress → completed；
    blockedBy: 必须先完成的前置任务 ID 列表。
    """

    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]


class TaskStore:
    """以 TASKS_DIR 下 task_xxxxxxxx.json 为单元的任务仓库。"""

    def __init__(self, directory: Path):
        self.directory = directory

    def _root(self, create: bool = False) -> Path:
        """解析任务目录绝对路径；create 时 mkdir。必须落在 RUNTIME_DIR 内。"""
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        root = self.directory.resolve()
        if not root.is_relative_to(RUNTIME_DIR.resolve()):
            raise ValueError("任务目录必须位于 RUNTIME_DIR 之内")
        return root

    def _path(self, task_id: str, create_root: bool = False) -> Path:
        """task_id → 目录内 .json 路径；校验 ID 格式并防止路径逃逸。"""
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError(f"非法任务 ID: {task_id!r}")
        root = self._root(create=create_root)
        path = (root / f"{task_id}.json").resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"非法任务 ID: {task_id!r}")
        return path

    def exists(self, task_id: str) -> bool:
        """任务文件是否存在（非法 ID 视为不存在）。"""
        try:
            return self._path(task_id).is_file()
        except ValueError:
            return False

    def create(self, subject: str, description: str = "") -> Task:
        """创建 pending 任务并独占写入新文件；ID 冲突则重试，最多 100 次。"""
        subject = subject.strip()
        if not subject:
            raise ValueError("任务主题不能为空")

        self._root(create=True)
        for _ in range(100):
            task = Task(
                id=f"task_{secrets.token_hex(4)}",
                subject=subject,
                description=description,
                status="pending",
                owner=None,
                blockedBy=[],
            )
            try:
                with self._path(task.id, create_root=True).open(
                    "x", encoding="utf-8"
                ) as handle:
                    json.dump(asdict(task), handle, indent=2, ensure_ascii=False)
                return task
            except FileExistsError:
                continue
        raise RuntimeError("无法分配唯一任务 ID")

    def _depends_on(self, task_id: str, target_id: str) -> bool:
        """task_id 是否直接或间接依赖 target_id（沿 blockedBy BFS）。"""
        pending = [task_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(self.load(current).blockedBy)
        return False

    def save(self, task: Task) -> None:
        """把 Task 覆盖写回对应 JSON。"""
        self._path(task.id, create_root=True).write_text(
            json.dumps(asdict(task), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self, task_id: str) -> Task:
        """按 ID 读盘并校验 id / status。"""
        data = json.loads(self._path(task_id).read_text(encoding="utf-8"))
        task = Task(**data)
        if task.id != task_id:
            raise ValueError(f"任务文件 ID 与 {task_id} 不一致")
        if task.status not in ("pending", "in_progress", "completed"):
            raise ValueError(f"非法任务状态: {task.status}")
        return task

    def list(self) -> list[Task]:
        """列出全部任务（按文件名排序）；目录不存在则 []。"""
        if not self.directory.exists():
            return []
        root = self._root()
        return [self.load(path.stem) for path in sorted(root.glob("task_*.json"))]

    def update_dependencies(self, task_id: str, add_blocked_by: list[str]) -> Task:
        """给 pending 且未认领的任务追加 blockedBy；拒绝自依赖与成环。"""
        if not isinstance(add_blocked_by, list) or not all(
            isinstance(item, str) for item in add_blocked_by
        ):
            raise ValueError("add_blocked_by 必须是字符串列表")

        task = self.load(task_id)
        if task.status != "pending" or task.owner is not None:
            raise ValueError("只能更新未开始且未认领的任务")

        dependencies = list(dict.fromkeys(add_blocked_by))
        for dependency in dependencies:
            if dependency == task_id:
                raise ValueError("不能依赖自身")
            if not self.exists(dependency):
                raise ValueError(f"依赖的任务不存在: {dependency}")
            if dependency not in task.blockedBy and self._depends_on(
                dependency, task_id
            ):
                raise ValueError(f"依赖循环: {task_id} -> {dependency}")

        task.blockedBy.extend(
            dependency
            for dependency in dependencies
            if dependency not in task.blockedBy
        )
        self.save(task)
        return task


TASKS = TaskStore(TASKS_DIR)


# ----- 面向工具 / 调用方的薄封装 -----


def create_task(subject: str, description: str = "") -> Task:
    """创建任务，返回 Task（含运行时生成的 id）。"""
    return TASKS.create(subject, description)


def update_task(task_id: str, addBlockedBy: list[str]) -> Task:
    """按 create_task 返回的 id 追加依赖；参数名 addBlockedBy 与工具 schema 对齐。"""
    return TASKS.update_dependencies(task_id, addBlockedBy)


def load_task(task_id: str) -> Task:
    """按 id 加载 Task。"""
    return TASKS.load(task_id)


def list_tasks() -> list[Task]:
    """返回全部 Task 列表。"""
    return TASKS.list()


def get_task(task_id: str) -> str:
    """按 id 返回格式化 JSON 字符串（给模型阅读）。"""
    return json.dumps(asdict(load_task(task_id)), indent=2, ensure_ascii=False)


def incomplete_dependencies(task: Task) -> list[str]:
    """列出尚未 completed 的前置 id；缺失或非法文件也视为未完成。"""
    incomplete = []
    for dependency in task.blockedBy:
        try:
            if load_task(dependency).status != "completed":
                incomplete.append(dependency)
        except (FileNotFoundError, ValueError, OSError):
            incomplete.append(dependency)
    return incomplete


def can_start(task_id: str) -> bool:
    """前置依赖是否都已完成（无未完成依赖则可 claim）。"""
    return not incomplete_dependencies(load_task(task_id))


def claim_task(task_id: str, owner: str = "agent") -> str:
    """认领 pending 且依赖已齐的任务 → in_progress；失败返回说明字符串。"""
    task = load_task(task_id)
    if task.status != "pending":
        return f"任务 {task_id} 状态为 {task.status}，无法认领"
    if task.owner is not None:
        return f"任务 {task_id} 已被 {task.owner} 认领"
    dependencies = incomplete_dependencies(task)
    if dependencies:
        return f"仍被阻塞: {dependencies}"
    task.owner = owner
    task.status = "in_progress"
    TASKS.save(task)
    print(f"  [claim] {task.subject} -> in_progress (owner: {owner})")
    return f"已认领 {task.id}（{task.subject}）"


def complete_task(task_id: str, owner: str = "agent") -> str:
    """由 owner 完成 in_progress 任务；若有新解锁的下游，附在返回文案中。"""
    task = load_task(task_id)
    if task.status != "in_progress":
        return f"任务 {task_id} 状态为 {task.status}，无法完成"
    if task.owner != owner:
        return f"任务 {task_id} 属于 {task.owner}，不是 {owner}"

    ready_before = {
        candidate.id
        for candidate in list_tasks()
        if candidate.status == "pending"
        and candidate.blockedBy
        and can_start(candidate.id)
    }
    task.status = "completed"
    TASKS.save(task)
    unblocked = [
        candidate.subject
        for candidate in list_tasks()
        if candidate.status == "pending"
        and candidate.blockedBy
        and candidate.id not in ready_before
        and can_start(candidate.id)
    ]
    print(f"  [complete] {task.subject}")
    message = f"已完成 {task.id}（{task.subject}）"
    if unblocked:
        message += f"\n新可开始: {', '.join(unblocked)}"
        print(f"  [unblocked] {', '.join(unblocked)}")
    return message
