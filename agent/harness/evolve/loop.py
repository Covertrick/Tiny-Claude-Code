"""离线自改进：失败 trace → 候选约束 → 行为对照 → 晋升或丢弃 → 可回滚。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.harness.effect import EffectClass, IntentStatus, RunStatus
from agent.harness.evolve.behavior import (
    ReplayCase,
    behavior_diff,
    cases_from_runs,
    default_replay_set,
)
from agent.harness.evolve.snapshots import (
    activate,
    current_rev,
    read_text,
    restore_snapshot,
    save_snapshot,
    write_text,
)
from agent.harness.store import HarnessStore, harness_root


def _log(event: dict) -> None:
    path = harness_root() / "evolve_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def failed_runs(store: HarnessStore | None = None) -> list:
    store = store or HarnessStore()
    bad = {RunStatus.FAILED.value, RunStatus.UNKNOWN.value, RunStatus.ABORTED.value}
    return [run for run in store.list_runs() if run.status in bad]


def mine_guardrail(runs: list) -> str:
    """从失败/未知意图提炼一条约束。不改模型权重。"""
    lines: list[str] = []
    for run in runs:
        for intent in run.intents:
            if intent.status not in (
                IntentStatus.UNKNOWN.value,
                IntentStatus.FAILED.value,
            ):
                continue
            if intent.effect_class == EffectClass.IRREVERSIBLE.value:
                lines.append(
                    f"- 技能 {intent.skill} 不可逆：结果未知时禁止自动重试，必须询问用户"
                )
            elif intent.usage and intent.usage.get("timed_out"):
                lines.append(f"- 技能 {intent.skill} 超时：不要把超时当成成功")
    if not lines:
        lines.append("- 不可逆技能结果未知时禁止自动重试，必须询问用户")
    # 去重并保持稳定顺序
    uniq = list(dict.fromkeys(lines))
    return "\n".join(uniq)


def propose_and_review(
    candidate: str,
    *,
    cases: list[ReplayCase] | None = None,
    store: HarnessStore | None = None,
) -> dict:
    """对照不通过则丢弃，通过则晋升并留下回滚点。"""
    old = read_text("guardrails.md")
    new = (old.rstrip() + "\n" + candidate.strip()).strip() + "\n"
    replay = list(cases) if cases is not None else default_replay_set()
    if cases is None:
        replay.extend(cases_from_runs(failed_runs(store)))
    report = behavior_diff(old, new, replay)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "candidate": candidate,
        "diff": report.to_dict(),
    }
    if not report.passed:
        event["action"] = "discard"
        _log(event)
        return event
    previous = save_snapshot(label="before-promote")
    write_text("guardrails.md", new)
    rev = save_snapshot(label="promoted")
    activate(rev)
    event["action"] = "promote"
    event["rev"] = rev
    event["rollback_of"] = previous
    _log(event)
    return event


def rollback(rev: str) -> dict:
    restore_snapshot(rev)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": "rollback",
        "rev": rev,
        "active": current_rev(),
    }
    _log(event)
    return event


def active_guardrails() -> str:
    return read_text("guardrails.md")
