import ast
import json

class ToolManager:
    """会话内待办列表：校验、覆盖更新，并渲染成给模型看的文本。"""

    def __init__(self):
        self.items: list[dict] = []

    def update(self, todos: list | str) -> str:
        """用完整列表覆盖当前 todos，返回 render() 文本。

        支持 list，或 JSON / Python 字面量字符串。同时最多一个 in_progress，最多 20 条。
        """
        if isinstance(todos, str):
            try:
                todos = json.loads(todos)
            except json.JSONDecodeError:
                try:
                    todos = ast.literal_eval(todos)
                except (SyntaxError, ValueError) as e:
                    raise ValueError(" todos 应该是一个有效的JSON字符串或Python列表") from e

        if not isinstance(todos, list):
            raise ValueError(" todos 应该是一个有效的JSON字符串或Python列表")
        if len(todos) > 20:
            raise ValueError(" todos 不能超过20个")

        validated = []
        in_progress_count = 0
        for index, todo in enumerate(todos):
            if not isinstance(todo, dict):
                raise ValueError(f"任务{index}应该是一个字典")

            content = str(todo.get("content", "")).strip()
            status = str(todo.get("status", "pending")).strip().lower()
            if not content:
                raise ValueError(f"任务{index}内容不能为空")
            if status not in ["pending", "in_progress", "completed"]:
                raise ValueError(f"任务{index}状态必须为pending, in_progress, completed")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"content": content, "status": status})

        if in_progress_count > 1:
            raise ValueError("不能同时进行多个任务")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """把待办渲染成 [ ] / [>] / [x] 列表文本。"""
        if not self.items:
            return "Error: 没有任务"

        lines = []
        for todo in self.items:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }[todo["status"]]
            lines.append(f"{marker} {todo['content']}")

        done = sum(todo["status"] == "completed" for todo in self.items)
        lines.append(f"\n已完成: {done}/{len(self.items)}")
        return "\n".join(lines)


TODO = ToolManager()


def run_todo_write(todos: list | str) -> str:
    """todo_write 工具入口：校验失败时返回 Error 字符串，不抛给模型循环。"""
    try:
        output = TODO.update(todos)
    except ValueError as e:
        return f"Error: {str(e)}"
    print(f"更新任务列表: \n{output}")
    return output
