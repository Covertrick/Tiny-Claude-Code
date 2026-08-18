import ast
import json

class ToolManager:
    """任务管理器"""

    def __init__(self):
        self.items: list[dict] = []

    def update(self, todos: list | str) -> str:
        """更新任务列表"""
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
        """渲染任务列表"""
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
    try:
        output = TODO.update(todos)
    except ValueError as e:
        return f"Error: {str(e)}"
    print(f"更新任务列表: \n{output}")
    return output
