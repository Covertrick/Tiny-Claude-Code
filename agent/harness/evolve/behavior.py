"""行为对照：同一回放集上比较旧/新约束，有回退则拒绝晋升。"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.harness.effect import EffectClass, RecoveryAction, recovery_for


@dataclass
class ReplayCase:
    name: str
    effect: str
    expect: str  # RecoveryAction value


@dataclass
class DiffReport:
    passed: bool
    regressions: list[str] = field(default_factory=list)
    checked: int = 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "regressions": list(self.regressions),
            "checked": self.checked,
        }


def action_under(guardrails: str, effect: str) -> str:
    """默认走 effect 决策表。约束文本只能收紧，不能放宽不可逆技能。"""
    base = recovery_for(effect).value
    text = guardrails or ""
    if "一律禁止重试" in text or "所有技能失败都禁止重试" in text:
        return RecoveryAction.ASK_USER.value
    if effect == EffectClass.IRREVERSIBLE.value and "禁止自动重试" in text:
        return RecoveryAction.ASK_USER.value
    return base


def cases_from_runs(runs: list) -> list[ReplayCase]:
    """用真实失败意图做回放：新约束不得改变这些 effect 的恢复动作。"""
    cases: list[ReplayCase] = []
    seen: set[tuple[str, str]] = set()
    for run in runs:
        for intent in getattr(run, "intents", []) or []:
            effect = str(getattr(intent, "effect_class", "") or "")
            status = str(getattr(intent, "status", "") or "")
            if status not in ("unknown", "failed") or not effect:
                continue
            key = (effect, status)
            if key in seen:
                continue
            seen.add(key)
            cases.append(
                ReplayCase(
                    name=f"trace:{getattr(run, 'run_id', '')}:{getattr(intent, 'skill', '')}",
                    effect=effect,
                    expect=recovery_for(effect).value,
                )
            )
    return cases


def default_replay_set() -> list[ReplayCase]:
    return [
        ReplayCase("idempotent_retry", EffectClass.IDEMPOTENT.value, RecoveryAction.RETRY.value),
        ReplayCase("retryable_same_key", EffectClass.RETRYABLE.value, RecoveryAction.RETRY_SAME_KEY.value),
        ReplayCase("irreversible_ask", EffectClass.IRREVERSIBLE.value, RecoveryAction.ASK_USER.value),
        ReplayCase("confirm_back", EffectClass.REQUIRES_CONFIRM.value, RecoveryAction.BACK_TO_CONFIRM.value),
    ]


def behavior_diff(
    old_text: str,
    new_text: str,
    cases: list[ReplayCase] | None = None,
) -> DiffReport:
    cases = cases if cases is not None else default_replay_set()
    regressions: list[str] = []
    for case in cases:
        new_action = action_under(new_text, case.effect)
        if new_action != case.expect:
            old_action = action_under(old_text, case.effect)
            regressions.append(
                f"{case.name}: 期望 {case.expect}，新约束得到 {new_action}（旧={old_action}）"
            )
    return DiffReport(passed=not regressions, regressions=regressions, checked=len(cases))
