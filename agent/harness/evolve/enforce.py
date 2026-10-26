"""把已晋升的 guardrails 用在执行期，而不是只写进提示词。

Run 绑定 harness_rev：回滚全局文案不会改掉这个 Run 已经冻结的约束。
"""

from __future__ import annotations

from agent.harness.effect import EffectClass
from agent.harness.evolve.snapshots import load_snapshot, read_text
from agent.harness.sandbox.ast_sandbox import run_ast


def guardrail_text_for_rev(rev: str) -> str:
    if rev and rev not in ("", "base"):
        try:
            files = (load_snapshot(rev).get("files") or {})
            if "guardrails.md" in files:
                return str(files.get("guardrails.md") or "")
        except FileNotFoundError:
            pass
    return read_text("guardrails.md")


def blocks_auto_retry(guardrails: str, effect: str) -> bool:
    if effect != EffectClass.IRREVERSIBLE.value:
        return False
    text = guardrails or ""
    return "禁止自动重试" in text or "一律禁止重试" in text


def postcondition_verdict(output: str) -> tuple[bool, str]:
    """postconditions.py 在 L1 沙箱里跑。约定定义 check(result) -> bool。"""
    script = read_text("postconditions.py").strip()
    if not script:
        return True, ""
    if "def check" not in script:
        return False, "postconditions.py 必须定义 check(result)"
    wrapped = script + "\nprint('PASS' if check(RESULT) else 'FAIL')"
    result = run_ast(wrapped, extra={"RESULT": (output or "")[:2000]})
    if not result.ok:
        return False, result.output
    if "FAIL" in (result.output or ""):
        return False, "postcondition 未通过"
    return True, ""
