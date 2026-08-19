from ..config import WORKDIR

DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777", "C:\\Windows", "C:\\Users", "/etc/"]


def permission_hook(name: str, args: dict) -> str | None:
    """PreToolUse：拦危险 bash，可疑命令与越界路径询问用户。

    拒绝时返回错误字符串；放行返回 None。
    """
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
    """PreToolUse：打印工具名与参数预览，不拦截。"""
    preview = str(list(args.values())[:2])[:50]
    print(f"\033[90m[HOOK]  工具: {name}, 参数: {preview} \033[0m")
    return None


def large_output_hook(name: str, result: str) -> None:
    """PostToolUse：输出超过 5000 字符时打印警告，不截断内容。"""
    if len(result) > 5000:
        print(f"\033[33m[HOOK]  工具: {name}, 输出过长: {len(result)} bytes\033[0m")
    return None


def context_inject_hook(query: str) -> None:
    """UserPromptSubmit：打印当前 WORKDIR（不改写用户输入）。"""
    print(f"\033[90m[HOOK] 当前工作目录: {WORKDIR}\033[0m")
    return None


def summary_hook(messages: list) -> None:
    """Stop：统计本轮 messages 中 role=tool 的条数并打印。"""
    tool_count = sum(1 for m in messages if m.get("role") == "tool")
    print(f"\033[32m[HOOK] 本次任务共使用{tool_count}个工具\033[0m")
    return None
