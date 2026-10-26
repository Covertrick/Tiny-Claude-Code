"""插件门面：启动只扫描清单；加载/卸载/重载交给 SkillRegistry。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.harness.registry import IndexedSkill, get_skill_registry


@dataclass
class PluginInfo:
    name: str
    version: str = "0.0.0"
    description: str = ""
    module: str = ""
    enabled: bool = True
    status: str = "indexed"


class PluginRegistry:
    """兼容旧调用：plugins 字典在访问时从索引现读。"""

    @property
    def plugins(self) -> dict[str, PluginInfo]:
        reg = get_skill_registry()
        out: dict[str, PluginInfo] = {}
        for package, entry in reg.by_package.items():
            out[package] = _info(entry)
        return out

    @property
    def tools(self):
        return get_skill_registry().api.tools


def _info(entry: IndexedSkill) -> PluginInfo:
    return PluginInfo(
        name=entry.package,
        version=entry.version,
        description=entry.description,
        module=f"plugins.{entry.package}.plugin",
        enabled=entry.status != "disabled",
        status=entry.status,
    )


def get_registry() -> PluginRegistry:
    return PluginRegistry()


def load_all() -> list[str]:
    """启动路径：只建索引，不 import 插件代码。"""
    return get_skill_registry().scan()


def reload_plugin(name: str) -> bool:
    return get_skill_registry().reload(name)
