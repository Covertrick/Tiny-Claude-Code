import os
import subprocess

from dotenv import load_dotenv

load_dotenv(override=True)

#request 代替Anthropic
import requests
import json

from pathlib import Path
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME")
END_POINT = f"{BASE_URL.rstrip('/')}/chat/completions"
WORKDIR = Path.cwd()


SYSTEM_PROMPT = f"你的Agent在 {os.getcwd()}运行，请根据系统提示完成任务"


#============Bash Tool 实现============
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: 危险操作被拒绝"
    
    try:
        r = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, timeout=120,
            # Windows 默认 GBK，读 UTF-8 文件会解码失败；用 utf-8 + replace 更稳
            encoding="utf-8", errors="replace",
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[:5000] if out else "命令执行成功，但未返回任何输出"
    except subprocess.TimeoutExpired:
        return "Error: 命令执行超时"
    except (FileNotFoundError, OSError) as e:
        return f"Error: 命令执行失败\n错误信息: {str(e)}"
    
#============Python Tool 实现============
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

# =============OPENAI TOOLS 定义============
TOOLS = [
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
    }
]

TOOL_HANDLERS = {
    "read": run_read,
    "write": run_write,
    "edit": run_edit,
    "glob": run_glob,
    "bash": run_bash,
}

#=========== 权限判断 ======================
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]

def check_deny_list(command: str) -> str | None:
    """第一重判断：检测禁止操作直接拒绝"""
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Error: 危险操作被拒绝: {pattern}"
    return None

PERMISSION_RULES = [
    {
        "tools":["read", "write", "edit"],
        "check": lambda args: not (WORKDIR /args.get("path", "")).resolve().is_relative_to(WORKDIR),
        "message": "Error: 路径超出工作目录范围"
    },
    {
        "tools": ["bash"],
        "check": lambda args: any(
            kw in args.get("command", "")
            for kw in [
                "rm ",
                "> /etc/",
                "chmod 777",
                "C:\\Windows",
                "C:\\Users",
                "/etc/",
            ]
        ),
        "message": "Error: 危险操作被拒绝",
    },
]

def check_rules(tool_name: str, args: dict) -> str | None:
    """第二重判断：检测工具权限"""
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"]:
            if rule["check"](args):
                return rule["message"]
    return None

def ask_user(tool_name: str, args: dict, reason: str) -> str | None:
    """第三重判断：询问用户是否继续"""
    print(f"\n\033[33m[permission] {reason}\033[0m")
    print(f"工具: {tool_name}, 参数: {args}")
    choice = input("是否继续？(y/n): ").strip().lower()
    return "allow" if choice == "y" else "deny"

def check_permission(name: str, args: dict) -> bool:
    """管道：三道闸门依次检查"""
    if name == "bash":
        reason = check_deny_list(args.get("command", ""))
        if reason:
            print(f"\n\033[31m[blocked] {reason}\033[0m")
            return False
    reason = check_rules(name, args)
    if reason:
        decision = ask_user(name, args, reason)
        if decision == "deny":
            return False
    return True

# ========== 核心Agent循环====================
def agent_loop(messages: list):
    while True:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model" : MODEL_NAME,
            "messages": messages,
            "tools": TOOLS,
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
            return
        
        # 处理tool_calls：用 TOOL_HANDLERS 统一分发
        tool_results = []
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")

            # 权限检查（传入已解析的 name / args）
            if not check_permission(name, args):
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": "Error: 操作被拒绝"
                })
                continue

            # 执行工具
            handler = TOOL_HANDLERS.get(name)

            if handler is None:
                output = f"Error: 未找到工具{name}的处理器"
            else:
                print (f"使用工具: {name} , 参数: {args}")
                output = handler(**args)
                print(f"工具{name}输出: {output}")

            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output
            })

        messages.extend(tool_results)

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

        history.append({"role": "user", "content": query})
        agent_loop(history)

        final_resp = history[-1]
        if final_resp.get("role") == "assistant" and final_resp.get("content"):
            print(final_resp["content"])
        print()
