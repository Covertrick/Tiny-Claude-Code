"""L1：AST 白名单。只挡语法层危险调用，不替代进程隔离。"""

from __future__ import annotations

import ast
import io

from agent.harness.sandbox.process_sandbox import SandboxResult

_BLOCKED_CALLS = {"open", "exec", "eval", "__import__", "compile", "getattr", "setattr"}
_BLOCKED_NODES = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)


def run_ast(code: str, extra: dict | None = None) -> SandboxResult:
    try:
        tree = ast.parse(code or "")
    except SyntaxError as e:
        return SandboxResult(ok=False, output=f"syntax: {e}", exit_code=1, usage={"sandbox": "ast"})
    for node in ast.walk(tree):
        if isinstance(node, _BLOCKED_NODES):
            return SandboxResult(
                ok=False,
                output=f"ast denied: {type(node).__name__}",
                exit_code=1,
                usage={"sandbox": "ast"},
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BLOCKED_CALLS:
                return SandboxResult(
                    ok=False,
                    output=f"ast denied: {node.func.id}()",
                    exit_code=1,
                    usage={"sandbox": "ast"},
                )
    buf = io.StringIO()

    def _print(*args):
        buf.write(" ".join(str(a) for a in args))

    safe = {
        "len": len,
        "range": range,
        "str": str,
        "int": int,
        "min": min,
        "max": max,
        "print": _print,
        "abs": abs,
    }
    scope = {"__builtins__": safe}
    for key, value in (extra or {}).items():
        if isinstance(value, (str, int, float, bool)):
            scope[str(key)] = value
    try:
        exec(compile(tree, "<ast-sandbox>", "exec"), scope, scope)
    except Exception as e:
        return SandboxResult(
            ok=False,
            output=str(e),
            exit_code=1,
            usage={"sandbox": "ast"},
        )
    return SandboxResult(
        ok=True,
        output=buf.getvalue(),
        exit_code=0,
        usage={"sandbox": "ast", "exit_code": 0},
    )
