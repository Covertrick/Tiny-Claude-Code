"""模拟具身后端：navigate 可重试，grasp 与发消息一样不可逆。"""

from __future__ import annotations

from agent.harness.effect import EffectClass, recovery_for, spoken_unknown


class EmbodiedSim:
    def __init__(self) -> None:
        self.held: str | None = None
        self.place = "origin"

    def navigate_to(self, place: str) -> dict:
        self.place = place or self.place
        return {
            "ok": True,
            "effect_class": EffectClass.IDEMPOTENT.value,
            "recovery": recovery_for(EffectClass.IDEMPOTENT).value,
            "place": self.place,
        }

    def grasp(self, obj: str, *, crashed: bool = False) -> dict:
        effect = EffectClass.IRREVERSIBLE
        if crashed:
            return {
                "ok": False,
                "status": "unknown",
                "effect_class": effect.value,
                "recovery": recovery_for(effect).value,
                "spoken": spoken_unknown(effect, skill="grasp"),
            }
        self.held = obj
        return {
            "ok": True,
            "effect_class": effect.value,
            "recovery": recovery_for(effect).value,
            "held": self.held,
        }
