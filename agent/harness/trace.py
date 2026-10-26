"""Run 轨迹：给 Admin / CLI 按 run_id 查看状态、意图和沙箱用量。"""

from __future__ import annotations

from agent.harness.store import HarnessStore


def _intent_view(intent) -> dict:
    usage = dict(intent.usage or {})
    return {
        "intent_id": intent.intent_id,
        "skill": intent.skill,
        "version": intent.version,
        "status": intent.status,
        "effect_class": intent.effect_class,
        "recovery": intent.recovery,
        "result_digest": intent.result_digest,
        "error": intent.error,
        "usage": usage,
    }


def trace_for(run_id: str, store: HarnessStore | None = None) -> dict | None:
    store = store or HarnessStore()
    run = store.load(run_id)
    if run is None:
        return None
    return {
        "run_id": run.run_id,
        "status": run.status,
        "channel": run.channel,
        "user_id": run.user_id,
        "group_id": run.group_id,
        "text": run.text,
        "harness_rev": getattr(run, "harness_rev", "") or "",
        "error": run.error,
        "reply": run.reply,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "intents": [_intent_view(it) for it in run.intents],
    }


def list_traces(limit: int = 30, store: HarnessStore | None = None) -> list[dict]:
    store = store or HarnessStore()
    rows = []
    for run in store.list_runs():
        rows.append(
            {
                "run_id": run.run_id,
                "status": run.status,
                "user_id": run.user_id,
                "text": (run.text or "")[:80],
                "harness_rev": getattr(run, "harness_rev", "") or "",
                "updated_at": run.updated_at,
            }
        )
    rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return rows[:limit]


def harness_rates(store: HarnessStore | None = None) -> dict:
    store = store or HarnessStore()
    runs = store.list_runs()
    total = len(runs)
    succeeded = sum(1 for r in runs if r.status == "succeeded")
    unknown_runs = sum(1 for r in runs if r.status == "unknown")
    sandbox_kills = 0
    for run in runs:
        for intent in run.intents:
            usage = intent.usage or {}
            if usage.get("sandbox") == "process" and (
                usage.get("timed_out") or int(usage.get("exit_code") or 0) != 0
            ):
                sandbox_kills += 1
    return {
        "runs": total,
        "run_success_rate": round(succeeded / total, 4) if total else 0.0,
        "unknown_rate": round(unknown_runs / total, 4) if total else 0.0,
        "sandbox_kill_count": sandbox_kills,
    }
