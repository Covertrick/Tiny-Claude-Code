import os
import subprocess
from pathlib import Path
from ..config import WORKDIR

#============Python Base Tools 实现============
def _decode_shell_output(data: bytes | None) -> str:
    """把 shell 字节输出解码成字符串。

    依次尝试 utf-8 / gbk / cp936 / latin-1，都失败则 utf-8 replace。
    """
    if not data:
        return ""
    for enc in ("utf-8", "gbk", "cp936", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def run_bash(command: str) -> str:
    """在 WORKDIR 下执行 shell 命令，返回合并后的 stdout/stderr（最多 5000 字）。"""
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
    """把相对路径解析成 WORKDIR 内的绝对路径；越界则抛 ValueError。"""
    resolved = (WORKDIR / path).resolve()
    if not resolved.is_relative_to(WORKDIR):
        raise ValueError(f"路径{path}超出工作目录{WORKDIR}范围")
    return resolved

def run_read(path:str, limit: int | None = None) -> str:
    """读取工作区内文件；limit 限制返回行数，超出部分用省略提示代替。"""
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[: limit] + [f"...还有{len(lines) - limit}行未显示"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: 读取文件失败\n错误信息: {str(e)}"

def run_write(path: str, content: str) -> str:
    """覆盖写入工作区内文件；父目录不存在时自动创建。"""
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents = True, exist_ok = True)
        file_path.write_text(content, encoding="utf-8")
        return f"文件写入{path}成功"
    except Exception as e:
        return f"Error: 写入文件失败\n错误信息: {str(e)}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """在文件中把 old_text 替换为 new_text（仅第一次匹配）。"""
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
    """在 WORKDIR 下按 glob 找文件，只返回仍落在工作区内的相对路径。"""
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