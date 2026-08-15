import os
import subprocess
from typing import Any

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
            trigger_hook("Stop", messages)
            return None
        
        # 处理tool_calls：用 TOOL_HANDLERS 统一分发
        tool_results = []
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]
            name = func["name"]
            args = json.loads(func.get("arguments") or "{}")

            # 触发PreToolUse Hook
            block = trigger_hook("PreToolUse", name, args)
            if block:
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": block
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

            # 触发PostToolUse Hook
            trigger_hook("PostToolUse", name, output)

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
        
        # 触发UserPromptSubmit Hook
        trigger_hook("UserPromptSubmit", query)


        history.append({"role": "user", "content": query})
        agent_loop(history)

        final_resp = history[-1]
        if final_resp.get("role") == "assistant" and final_resp.get("content"):
            print(final_resp["content"])
        print()
