"""Skill 执行链：precondition → sandbox_policy → postcondition。账本由 execute_tool 写。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent.harness.sandbox.ast_sandbox import run_ast
from agent.harness.sandbox.process_sandbox import SandboxResult, run_process


def _policy(snapshot: dict | None, fallback: str = "none") -> str:
    if not snapshot:
        return fallback
    return str(snapshot.get("sandbox_policy") or fallback)


def _cwd_for(args: dict) -> Path:
    raw = args.get("cwd")
    if raw:
        return Path(str(raw))
    from agent.config import FILES_DIR

    path = Path(FILES_DIR) / "_sandbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dispatch(
    name: str,
    args: dict,
    handler: Callable[..., str] | None,
    snapshot: dict | None,
) -> tuple[str, dict]:
    """返回 (文本, usage)。不可信脚本（sandbox_policy=process 或 untrusted=True）强制 L2。"""
    meta = dict(snapshot or {})
    policy = _policy(meta, "none")
    if args.get("untrusted") or args.get("code") and policy == "none" and name.startswith("run_"):
        policy = "process"
    if args.get("untrusted"):
        policy = "process"

    if policy == "process":
        code = str(args.get("code") or args.get("script") or "")
        if not code.strip():
            return "precondition 失败：缺少 code", {"sandbox": "process", "precondition": False}
        result = run_process(code, cwd=_cwd_for(args), timeout=float(args.get("timeout") or 5))
        text = result.output or f"exit {result.exit_code}"
        if not result.ok:
            text = f"沙箱拒绝或失败（exit={result.exit_code}）\n{text}"
        return text, result.usage

    if policy == "ast":
        code = str(args.get("code") or "")
        if not code.strip():
            return "precondition 失败：缺少 code", {"sandbox": "ast", "precondition": False}
        result = run_ast(code)
        text = result.output if result.ok else f"沙箱拒绝或失败\n{result.output}"
        return text, result.usage

    if handler is None:
        return f"Error: Unknown tool: {name}", {"sandbox": "none"}
    call_args = dict(args)
    for key in ("run_in_background", "untrusted", "code", "script", "cwd", "timeout"):
        call_args.pop(key, None)
    output = str(handler(**call_args))
    try:
        from agent.harness.evolve.enforce import postcondition_verdict

        ok, why = postcondition_verdict(output)
    except Exception as e:
        ok, why = True, ""
        print(f"[harness] postcondition 跳过: {e}")
    usage = {"sandbox": "none", "exit_code": 0 if ok else 1, "postcondition": ok}
    if not ok:
        return f"postcondition 失败：{why}", usage
    return output, usage
