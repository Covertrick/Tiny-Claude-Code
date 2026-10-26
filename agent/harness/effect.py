"""副作用类别与 UNKNOWN 恢复决策（写死，不靠模型临场猜）。"""

from __future__ import annotations

from enum import Enum


class EffectClass(str, Enum):
    IDEMPOTENT = "idempotent"
    RETRYABLE = "retryable"
    IRREVERSIBLE = "irreversible"
    REQUIRES_CONFIRM = "requires_confirm"


class RunStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    TOOL_PENDING = "tool_pending"
    TOOL_RUNNING = "tool_running"
    AWAITING_CONFIRM = "awaiting_confirm"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


class IntentStatus(str, Enum):
    PLANNED = "planned"
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


TERMINAL_RUN = {
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.ABORTED,
}

# UNKNOWN 仍算未结案：需要人工确认或策略收口
OPEN_RUN = set(RunStatus) - TERMINAL_RUN


class RecoveryAction(str, Enum):
    RETRY = "retry"                 # 自动重试（有上限）
    RETRY_SAME_KEY = "retry_same_key"
    ASK_USER = "ask_user"           # 不自动重做
    BACK_TO_CONFIRM = "back_to_confirm"


def recovery_for(effect: EffectClass | str) -> RecoveryAction:
    """UNKNOWN 默认策略表。"""
    key = effect.value if isinstance(effect, EffectClass) else str(effect)
    table = {
        EffectClass.IDEMPOTENT.value: RecoveryAction.RETRY,
        EffectClass.RETRYABLE.value: RecoveryAction.RETRY_SAME_KEY,
        EffectClass.IRREVERSIBLE.value: RecoveryAction.ASK_USER,
        EffectClass.REQUIRES_CONFIRM.value: RecoveryAction.BACK_TO_CONFIRM,
    }
    return table.get(key, RecoveryAction.ASK_USER)


def spoken_unknown(effect: EffectClass | str, *, skill: str = "") -> str:
    """给用户的一句说明；禁止沉默。"""
    action = recovery_for(effect)
    name = skill or "刚才那步"
    if action is RecoveryAction.RETRY:
        return f"「{name}」中途断了，这步可以重做，我再试一次。"
    if action is RecoveryAction.RETRY_SAME_KEY:
        return f"「{name}」没确认是否写完，我会按同一次请求补做，不会另开一份。"
    if action is RecoveryAction.BACK_TO_CONFIRM:
        return f"「{name}」还停在确认前，我不会擅自执行，你要的话再说一声确认。"
    return (
        f"「{name}」不确定有没有做成（可能已经发出或改过）。"
        f"我不会自动再做一遍，你回我「已经好了」或「再来一次」。"
    )
