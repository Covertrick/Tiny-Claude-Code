import os
import subprocess
from typing import Any

from dotenv import load_dotenv

import ast

load_dotenv(override=True)

#request 代替Anthropic
import requests
import json

from pathlib import Path

import yaml
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME")
END_POINT = f"{BASE_URL.rstrip('/')}/chat/completions"
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / 'skills'


#============Skill catalog ==============
class SkillLoader:
    """技能加载器"""
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills: dict[str, dict[str, str]] = {}
        self.scan()

    
    @staticmethod
    def parse_frontmatter(text: str) -> tuple[dict, str]:
        """解析 YAML frontmatter，返回 (元数据字典, 正文)，如果解析失败则返回空字典和原始文本"""
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != "---":
            return {}, text

        # 从第 2 行起找结束的 --- 的下标；找不到则视为无 frontmatter
        closing_index = next(
            (index for index, line in enumerate(lines[1:], start=1)
             if line.rstrip("\r\n") == "---"),
            None,
        )
        if closing_index is None:
            return {}, text
        # 提取 frontmatter 和 body
        frontmatter = "".join(lines[1:closing_index])
        body = "".join(lines[closing_index + 1 : ])

        try:
            metadata = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return metadata, body

    def scan(self) -> None:
        """扫描技能目录，加载所有技能"""
        self.skills.clear()
        if not self.skills_dir.exists():
            return None
        
        skills_root = self.skills_dir.resolve()
        for manifest in sorted(self.skills_dir.glob("*/SKILL.md")):
            if (not manifest.is_file()
                    or not manifest.resolve().is_relative_to(skills_root)):
                continue
            content = manifest.read_text(encoding = "utf-8")
            metadata, body = self.parse_frontmatter(content)
            # 提取技能名称
            raw_name = metadata.get("name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            name = name or manifest.parent.name
            # 提取技能描述
            raw_description = metadata.get("description")
            description = raw_description.strip() if isinstance(raw_description, str) else ""
            description = description or body.split("\n", 1)[0]
            description = " ".join(str(description).lstrip("# ").split())
            self.skills[name] = {
                "name": name,
                "description": description,
                "content": content
            }
    
    def catalog(self) -> str:
        """返回技能目录"""
        if not self.skills:
            return "Error: 没有找到技能"
        return "\n".join(
            f"- {skill['name']}: {skill['description']}"
            for skill in self.skills.values()
        )
    
    def load(self, name: str) -> str:
        """加载技能"""
        skill = self.skills.get(name)
        if skill:
            return skill["content"]
        available = ",".join(self.skills) or "none"
        return f"Error: 未找到技能 {name}\n可用技能: {available}"

#实例化技能加载器
SKILL_LOADER = SkillLoader(SKILLS_DIR)

def build_system_prompt() -> str:
    """构建系统提示词"""
    return (
        f"你是一个在 {WORKDIR} 运行的编程 Agent。"
        "开始任何多步骤任务前，先用 todo_write 规划步骤；"
        "执行过程中及时更新任务状态（pending / in_progress / completed）。"
        "同一时间只能有一个 in_progress。"
        "遇到需要专注探索或相对独立的子任务时，使用 task 交给子 Agent 执行，"
        "你根据子 Agent 返回的总结继续决策；简单一步操作可直接使用基础工具。"
        f"技能可用:\n{SKILL_LOADER.catalog()}\n\n"
        "使用 load_skill 加载技能时，使用 load_skill 读取完整的技能说明。"
    )

SYSTEM_PROMPT = build_system_prompt()

SUB_SYSTEM_PROMPT = (
    f"你是一个在 {WORKDIR} 运行的编程 Agent。"
    "完成交给你的任务,然后返回一个简洁的总结。"
)



#============Python Base Tools 实现============
def _decode_shell_output(data: bytes | None) -> str:
    """Windows shell 多为 GBK，文件/部分工具为 UTF-8；按序尝试解码。"""
    if not data:
        return ""
    for enc in ("utf-8", "gbk", "cp936", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: 危险操作被拒绝"
    
    try:
        r = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, timeout=120,
        )
        out = (_decode_shell_output(r.stdout) + _decode_shell_output(r.stderr)).strip()
        return out[:5000] if out else "命令执行成功，但未返回任何输出"
    except subprocess.TimeoutExpired:
        return "Error: 命令执行超时"
    except (FileNotFoundError, OSError) as e:
        return f"Error: 命令执行失败\n错误信息: {str(e)}"
    
def safe_path(path: str) -> Path:
    """检查路径是否在工作目录内"""
    path = (WORKDIR / path)
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"路径{path}超出工作目录{WORKDIR}范围")
    return path

def run_read(path:str, limit: int | None = None) -> str:
    """读取文件内容，支持限制行数"""
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[: limit] + [f"...还有{len(lines) - limit}行未显示"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: 读取文件失败\n错误信息: {str(e)}"

def run_write(path: str, content: str) -> str:
    """写入文件内容"""
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents = True, exist_ok = True)
        file_path.write_text(content, encoding="utf-8")
        return f"文件写入{path}成功"
    except Exception as e:
        return f"Error: 写入文件失败\n错误信息: {str(e)}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件内容"""
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding = "utf-8")
        if old_text not in text:
            return f"Error: 文件{path}中没有找到旧文本"
        file_path.write_text(text.replace(old_text, new_text, 1), encoding = "utf-8")
        return f"文件{path}编辑成功"
    except Exception as e:
        return f"Error: 编辑文件失败\n错误信息: {str(e)}"

def run_glob(pattern:str) -> str:
    """查找文件"""
    import glob as g
    try:
        results = []
        for match in g.glob(pattern, root_dir = WORKDIR):
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "Error: 没有找到文件"
    except Exception as e:
        return f"Error: 查找文件失败\n错误信息: {str(e)}"

#============Base Tools Handler ================
BASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "在本地执行shell命令",
            "parameters": {
                "type": "object",
                "properties" :{
                    "command": {"type": "string", "description": "要执行的shell命令"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要读取的文件路径"},
                    "limit": {"type": "integer", "description": "要读取的行数，默认不限制"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "写入文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要写入的文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "编辑文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要编辑的文件路径"},
                    "old_text": {"type": "string", "description": "要编辑的旧文本"},
                    "new_text": {"type": "string", "description": "要编辑的新文本"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "查找文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "要查找的文件模式"}
                },
                "required": ["pattern"]
            }
        }
    },
]

BASE_HANDLERS = {
    "read": run_read,
    "write": run_write,
    "edit": run_edit,
    "glob": run_glob,
    "bash": run_bash,
}
#=============Hook系统====================
HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": []
}

def register_hook(event: str, callback) -> None:
    """注册Hook"""
    HOOKS[event].append(callback)

def trigger_hook(event: str, *args) -> Any | None:
    """触发Hook"""
    for callback in HOOKS[event]:
        result = callback(* args)
        if result is not None:
            return result
    return None

#=========== 权限判断 ======================
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777", "C:\\Windows", "C:\\Users", "/etc/"]

def permission_hook(name: str, args: dict) -> str | None:
    """PreToolUse: 三重判断：禁止列表、危险操作、询问用户"""
    if name == "bash":
        for pattern in DENY_LIST:
            if pattern in args.get("command", ""):
                print(f"\n\033[31m[blocked] {pattern}\033[0m")
                return "Error: 危险操作被拒绝"
        for kw in DESTRUCTIVE:
            if kw in args.get("command", ""):
                print(f"\n\033[31m[blocked] {kw}\033[0m")
                print(f"工具: {name}, 参数: {args}")
                choice = input("是否继续？(y/n): ").strip().lower()
                if choice not in ("y", "yes"):
                    return "Error: 操作被拒绝"
    
    if name in ["read", "write", "edit"]:
        check_path = (WORKDIR / args.get("path", "")).resolve().is_relative_to(WORKDIR)
        if not check_path:
            print(f"\n\033[31m[blocked] {args.get('path', '')}\033[0m")
            print(f"工具: {name}, 参数: {args}")
            choice = input("是否继续？(y/n): ").strip().lower()
            if choice not in ("y", "yes"):
                return "Error: 操作被拒绝"
    
    return None

def log_hook(name: str, args: dict) -> None:
    """PreToolUse: 记录每次工具使用日志"""
    preview = str(list(args.values())[:2])[:50] # 参数预览,避免刷屏
    print(f"\033[90m[HOOK]  工具: {name}, 参数: {preview} \033[0m")
    return None

def large_output_hook(name: str, result: str) -> None:
    """PostToolUse: 处理大型输出"""
    if len(result) > 5000:
        print(f"\033[33m[HOOK]  工具: {name}, 输出过长: {len(result)} bytes\033[0m")
    return None

def context_inject_hook(query: str) -> None:
    """UserPromptSubmit: 在用户输入前注入工作目录信息"""
    print(f"\033[90m[HOOK] 当前工作目录: {WORKDIR}\033[0m")
    return None

def summary_hook(messages: list) -> None:
    """Stop: 在Agent停止时打印总结"""
    tool_count = sum(1 for m in messages if m.get("role") == "tool")
    print(f"\033[32m[HOOK] 本次任务共使用{tool_count}个工具\033[0m")
    return None

# 注册Hook
register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)

#============= 工具执行总流程 =============

def execute_tool(name: str, args: dict, handlers: dict) -> str:
    """封装执行工具的预处理、执行、后处理流程"""
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


#=============带有新消息的SubAgent循环============
SUB_TOOLS = list(BASE_TOOLS)
SUB_HANDLERS = dict(BASE_HANDLERS)

def extract_text(content: Any) -> str:
    """从 assistant 的 content 提取最终文本（给父 Agent 的 tool_result）。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)

def run_subagent(content: str) -> str:
    """执行子Agent，返回最终文本"""
    print("\n\033[35m[SubAgent] 开始执行任务\033[0m")
    messages = [
        {"role": "system", "content": SUB_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    for _ in range(30): # 最多执行30轮
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model" : MODEL_NAME,
            "messages": messages,
            "tools": SUB_TOOLS,
            "tool_choice": "auto",
            "max_tokens": 5000
        }

        response = requests.post(END_POINT, headers = headers, json = payload, timeout = 180)
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        msg = choice["message"]

        messages.append(msg)

        # 如果不是tool_calls，则返回结果
        if not msg.get("tool_calls"):
            trigger_hook("Stop", messages)
            print(f"\n\033[35m[SubAgent] 任务执行完成\033[0m")
            return extract_text(msg.get("content", ""))
        
        # 处理tool_calls：用 SUB_HANDLERS 统一分发
        tool_results = []
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")
            
            output = execute_tool(name, args, SUB_HANDLERS)


            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output
            })
        messages.extend(tool_results)
    print(f"\n\033[35m[SubAgent] 任务执行完成\033[0m")
    return "Sub Agent 执行30轮后，没有返回结果"
        

#============= 结构化状态，模型更新============
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
        
        # 逐条校验任务列表
        validated = [] # 有效任务
        in_progress_count = 0 # 进行中任务数
        for index, todo in enumerate(todos):
            if not isinstance(todo, dict):
                raise ValueError(f"任务{index}应该是一个字典")
            
            content = str(todo.get("content", "")).strip() # 任务内容
            status = str(todo.get("status", "pending")).strip().lower() # 任务状态
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

#注册ToolManager
TODO = ToolManager()

def run_todo_write(todos: list | str) ->  str:
    try:
        output = TODO.update(todos)
    except ValueError as e:
        return f"Error: {str(e)}"
    print(f"更新任务列表: \n{output}")
    return output


# =============总 TOOLS 定义============
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
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "创建并管理当前会话的任务列表",
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
                                    "description": "任务内容"
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "任务状态"
                                }
                            },
                            "required": ["content", "status"]
                        }
                    }
                },
                "required": ["todos"]
            }
        }
    },
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
                "required": ["name"]
            }
        }
    }
]

TOOL_HANDLERS = {
    **BASE_HANDLERS,
    "task": run_subagent,
    "todo_write": run_todo_write,
    "load_skill": SKILL_LOADER.load,
}


# ========== 核心Agent循环====================
def agent_loop(messages: list):
    rounds_since_todo = 0 # 多少轮没有使用todo_write工具

    while True:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model" : MODEL_NAME,
            "messages": messages,
            "tools": TASK_TOOLS,
            "tool_choice": "auto",
            "max_tokens": 5000
        }

        response = requests.post(END_POINT, headers = headers, json = payload, timeout = 180)
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        msg = choice["message"]

        # 将assistant的回复添加到messages中
        messages.append(msg)

        # 如果不是tool_calls，则返回结果
        if not msg.get("tool_calls"):
            trigger_hook("Stop", messages)
            return None
        
        # 处理tool_calls：用 TOOL_HANDLERS 统一分发
        tool_results = []
        used_todo = False # 是否使用了todo_write工具
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")

            # 执行工具
            output = execute_tool(name, args, TOOL_HANDLERS)

            if name == "todo_write":
                used_todo = True
            
            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output
            })
        
        messages.extend(tool_results)
        # 如果使用了todo_write工具，则重置轮数，否则增加轮数
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        # 连续 3 轮没用 todo_write：追加提醒（不要用 role=tool，没有对应 tool_call_id）
        if rounds_since_todo >= 3:
            messages.append({
                "role": "user",
                "content": "<reminder>请用 todo_write 更新你的任务列表。</reminder>",
            })
            rounds_since_todo = 0
            print("\033[33m[reminder] 已提醒模型更新 todos\033[0m")

# ========== 终端交互入口 ==========
if __name__ == "__main__":
    print(f"Agent正在运行，模型: {MODEL_NAME}")
    print("输入任务，回车发送，输入exit退出。 \n")

    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m") 
        except (EOFError, KeyboardInterrupt):
            break
        if query.lower() in ("exit", ""):
            break
        
        # 触发UserPromptSubmit Hook
        trigger_hook("UserPromptSubmit", query)


        history.append({"role": "user", "content": query})
        agent_loop(history)

        final_resp = history[-1]
        if final_resp.get("role") == "assistant" and final_resp.get("content"):
            print(final_resp["content"])
        print()
