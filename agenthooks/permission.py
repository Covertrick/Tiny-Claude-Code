from ..config import WORKDIR

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
    preview = str(list(args.values())[:2])[:50]
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
