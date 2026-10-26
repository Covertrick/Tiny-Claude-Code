"""Harness Runtime（P0）：Session/Run 状态机、Skill 快照、intent 账本、UNKNOWN 恢复。"""

from __future__ import annotations

import contextvars
from typing import Any

from agent.harness.effect import (
    OPEN_RUN,
    EffectClass,
    IntentStatus,
    RecoveryAction,
    RunStatus,
    recovery_for,
    spoken_unknown,
)
from agent.harness.qq_skills import QQ_SKILL_MANIFESTS, manifest_for
from agent.harness.store import (
    HarnessStore,
    IntentRecord,
    RunRecord,
    args_hash,
    new_id,
    session_key,
)

_store = HarnessStore()
_current: contextvars.ContextVar[RunRecord | None] = contextvars.ContextVar(
    "harness_run", default=None
)

# 幂等/可重试的自动重试上限（同一 intent 不会在同一次进程内死循环；这里只记策略）
MAX_AUTO_RETRY = 2


def current_run() -> RunRecord | None:
    return _current.get()


def skill_snapshot() -> dict[str, Any]:
    snap = {
        name: {**m.snapshot(), "source": "builtin"}
        for name, m in QQ_SKILL_MANIFESTS.items()
    }
    try:
        from agent.harness.registry import get_skill_registry

        snap.update(get_skill_registry().snapshot_map())
    except Exception as e:
        print(f"[harness] 插件索引跳过: {e}")
    return snap


class HarnessRuntime:
    def __init__(self, store: HarnessStore | None = None) -> None:
        self.store = store or _store

    def start_run(
        self,
        *,
        channel: str,
        user_id: str,
        group_id: str | None,
        text: str,
        require_contract: bool = True,
    ) -> RunRecord:
        key = session_key(channel, user_id, group_id)
        run = RunRecord(
            run_id=new_id("run"),
            session_key=key,
            channel=channel,
            user_id=str(user_id),
            group_id=str(group_id or "private"),
            text=(text or "")[:500],
            status=RunStatus.PLANNING.value,
            skill_snapshot=skill_snapshot(),
            require_contract=require_contract,
            created_at="",
        )
        try:
            from agent.harness.evolve.snapshots import current_rev, read_text

            run.harness_rev = current_rev()
            run.guardrail_text = read_text("guardrails.md")
        except Exception:
            run.harness_rev = ""
            run.guardrail_text = ""
        from agent.harness.store import _now

        run.created_at = _now()
        self.store.save(run)
        try:
            from agent.harness.registry import get_skill_registry

            get_skill_registry().acquire_snapshot(run.run_id, run.skill_snapshot)
        except Exception as e:
            print(f"[harness] acquire 跳过: {e}")
        _current.set(run)
        return run

    def set_status(self, run: RunRecord, status: RunStatus, *, error: str = "") -> None:
        run.status = status.value
        if error:
            run.error = error[:500]
        self.store.save(run)

    def finish(
        self,
        run: RunRecord,
        *,
        status: RunStatus,
        reply: str = "",
        error: str = "",
    ) -> None:
        if status is RunStatus.SUCCEEDED and any(
            it.status == IntentStatus.UNKNOWN.value for it in run.intents
        ):
            status = RunStatus.UNKNOWN
        run.status = status.value
        run.reply = (reply or "")[:2000]
        if error:
            run.error = error[:500]
        self.store.save(run)
        self._release(run)
        if _current.get() is run:
            _current.set(None)

    def _release(self, run: RunRecord) -> None:
        try:
            from agent.harness.registry import get_skill_registry

            get_skill_registry().release_snapshot(run.run_id, run.skill_snapshot)
        except Exception as e:
            print(f"[harness] release 跳过: {e}")

    def begin_intent(self, run: RunRecord, name: str, args: dict) -> IntentRecord | str:
        """返回 Intent，或返回拒绝文案（str）。"""
        manifest = None
        snap = (run.skill_snapshot or {}).get(name) or {}
        if snap:
            manifest = manifest_for(name)
        elif run.require_contract:
            manifest = manifest_for(name)
        if run.require_contract and manifest is None and not snap:
            return (
                f"Error: Skill「{name}」没有契约，已拒绝执行。"
                "请先补 effect_class / 权限后再调用。"
            )
        # 快照绑定：Run 创建时的版本，不跟随后续热更新
        version = str(snap.get("version") or (manifest.version if manifest else "0"))
        effect = str(
            snap.get("effect_class")
            or (manifest.effect_class.value if manifest else EffectClass.IRREVERSIBLE.value)
        )
        digest = args_hash(args)
        idem = f"{name}:{digest}"
        try:
            from agent.harness.evolve.enforce import blocks_auto_retry
            from agent.harness.effect import spoken_unknown

            rules = getattr(run, "guardrail_text", "") or ""
            if blocks_auto_retry(rules, effect):
                for old in run.intents:
                    if (
                        old.skill == name
                        and old.idempotency_key == idem
                        and old.status
                        in (IntentStatus.UNKNOWN.value, IntentStatus.FAILED.value)
                    ):
                        return spoken_unknown(effect, skill=name)
        except Exception as e:
            print(f"[harness] guardrail 检查跳过: {e}")
        # 同一 Run 内，幂等成功过的不再执行
        for old in run.intents:
            if (
                old.skill == name
                and old.idempotency_key == idem
                and old.status == IntentStatus.SUCCEEDED.value
                and effect in (
                    EffectClass.IDEMPOTENT.value,
                    EffectClass.RETRYABLE.value,
                )
            ):
                return f"（幂等命中，跳过重复执行）{old.result_digest}"

        intent = IntentRecord(
            intent_id=new_id("int"),
            run_id=run.run_id,
            skill=name,
            version=version,
            args_hash=digest,
            idempotency_key=idem,
            status=IntentStatus.STARTED.value,
            effect_class=effect,
            recovery=recovery_for(effect).value,
        )
        from agent.harness.store import _now

        intent.started_at = _now()
        run.intents.append(intent)
        run.status = RunStatus.TOOL_RUNNING.value
        # 先落盘再执行：崩溃后这里停在 STARTED
        self.store.save(run)
        return intent

    def complete_intent(
        self,
        run: RunRecord,
        intent: IntentRecord,
        *,
        status: IntentStatus,
        result: str = "",
        error: str = "",
        usage: dict | None = None,
    ) -> str:
        from agent.harness.store import _now

        intent.status = status.value
        intent.finished_at = _now()
        intent.result_digest = (result or error or "")[:240]
        intent.error = error[:300]
        if usage:
            intent.usage = dict(usage)
        if status is IntentStatus.UNKNOWN:
            run.status = RunStatus.UNKNOWN.value
            note = spoken_unknown(intent.effect_class, skill=intent.skill)
            self.store.push_notice(run.session_key, note)
            self.store.save(run)
            return note
        if status is IntentStatus.FAILED and run.status == RunStatus.TOOL_RUNNING.value:
            run.status = RunStatus.PLANNING.value
        self.store.save(run)
        return ""

    def recover_open_runs(self) -> list[str]:
        """启动时把停在 STARTED / 非终态的 Run 收口。

        - 只有规划、没有已开始的副作用 → ABORTED（整轮可重来）
        - 有 STARTED 的意图 → 标 UNKNOWN，按 effect_class 给用户一句话
        """
        notices: list[str] = []
        for run in self.store.list_runs():
            try:
                status = RunStatus(run.status)
            except ValueError:
                continue
            if status not in OPEN_RUN:
                continue
            if status is RunStatus.UNKNOWN:
                # 已经收口过，避免每次启动重复刷通知
                continue
            started = [
                it
                for it in run.intents
                if it.status in (IntentStatus.STARTED.value, IntentStatus.PLANNED.value)
            ]
            if not started:
                if status in (
                    RunStatus.CREATED,
                    RunStatus.PLANNING,
                    RunStatus.TOOL_PENDING,
                ):
                    run.status = RunStatus.ABORTED.value
                    run.error = "进程中断，尚未产生副作用"
                else:
                    # 意图都已收口，只是 Run 没写终态
                    run.status = RunStatus.SUCCEEDED.value
                    run.error = ""
                self.store.save(run)
                self._release(run)
                continue
            for it in started:
                it.status = IntentStatus.UNKNOWN.value
                it.error = it.error or "执行中断，结果未知"
                action = recovery_for(it.effect_class)
                it.recovery = action.value
                note = spoken_unknown(it.effect_class, skill=it.skill)
                if action in (RecoveryAction.RETRY, RecoveryAction.RETRY_SAME_KEY):
                    note = note + f"（自动重试上限 {MAX_AUTO_RETRY} 次，需用户再次发起）"
                notices.append(note)
                self.store.push_notice(run.session_key, note)
            run.status = RunStatus.UNKNOWN.value
            run.error = "存在未确认的工具副作用"
            self.store.save(run)
            self._release(run)
        return notices

    def active_runs(self) -> list[dict]:
        rows = []
        for run in self.store.list_runs():
            try:
                status = RunStatus(run.status)
            except ValueError:
                continue
            if status in OPEN_RUN:
                rows.append(
                    {
                        "run_id": run.run_id,
                        "status": run.status,
                        "user_id": run.user_id,
                        "text": run.text[:80],
                    }
                )
        return rows

    def unknown_count(self) -> int:
        n = 0
        for run in self.store.list_runs():
            if run.status == RunStatus.UNKNOWN.value:
                n += 1
            n += sum(1 for it in run.intents if it.status == IntentStatus.UNKNOWN.value)
        return n

    def consume_notices(self, channel: str, user_id: str, group_id: str | None) -> list[str]:
        return self.store.consume_notices(session_key(channel, user_id, group_id))


def get_runtime() -> HarnessRuntime:
    return HarnessRuntime()
