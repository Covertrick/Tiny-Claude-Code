"""Skill 最小契约。缺契约的 Skill 不得进入 QQ 生产路径。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agent.harness.effect import EffectClass


@dataclass
class SkillManifest:
    name: str
    version: str
    effect_class: EffectClass
    permissions: list[str] = field(default_factory=list)
    sandbox_policy: str = "none"  # none | ast | process（P0 只记录，执行仍在进程内）
    description: str = ""

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "effect_class": self.effect_class.value,
            "permissions": list(self.permissions),
            "sandbox_policy": self.sandbox_policy,
        }
