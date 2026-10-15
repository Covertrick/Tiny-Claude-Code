"""importlib 动态加载 plugins/*（Phase 3 骨架，已可扫描注册）。"""

from __future__ import annotations

import importlib
import json
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class PluginInfo:
    name: str
    version: str = "0.0.0"
    description: str = ""
    module: str = ""
    enabled: bool = True


@dataclass
class PluginRegistry:
    tools: dict[str, Callable[..., str]] = field(default_factory=dict)
    interceptors: list[Callable[..., str | None]] = field(default_factory=list)
    plugins: dict[str, PluginInfo] = field(default_factory=dict)

    def register_tool(self, name: str, handler: Callable[..., str]) -> None:
        self.tools[name] = handler

    def register_interceptor(self, fn: Callable[..., str | None]) -> None:
        self.interceptors.append(fn)


_REGISTRY = PluginRegistry()
_ROOT = Path(__file__).resolve().parent


def get_registry() -> PluginRegistry:
    return _REGISTRY


def load_all() -> list[str]:
    loaded = []
    if str(_ROOT.parent) not in sys.path:
        sys.path.insert(0, str(_ROOT.parent))
    for info in pkgutil.iter_modules([str(_ROOT)]):
        if info.name.startswith("_") or info.name in ("loader",):
            continue
        name = info.name
        try:
            mod = importlib.import_module(f"plugins.{name}.plugin")
            manifest_path = _ROOT / name / "manifest.json"
            meta = {"name": name, "version": "0.0.0", "description": ""}
            if manifest_path.is_file():
                meta.update(json.loads(manifest_path.read_text(encoding="utf-8")))
            if hasattr(mod, "register"):
                mod.register(_REGISTRY)
            _REGISTRY.plugins[name] = PluginInfo(
                name=meta.get("name") or name,
                version=str(meta.get("version") or "0.0.0"),
                description=str(meta.get("description") or ""),
                module=f"plugins.{name}.plugin",
                enabled=True,
            )
            loaded.append(name)
            print(f"[plugins] loaded {name}")
        except Exception as e:
            print(f"[plugins] skip {name}: {e}")
    return loaded


def reload_plugin(name: str) -> bool:
    mod_name = f"plugins.{name}.plugin"
    try:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)
        mod = sys.modules[mod_name]
        if hasattr(mod, "register"):
            mod.register(_REGISTRY)
        print(f"[plugins] reloaded {name}")
        return True
    except Exception as e:
        print(f"[plugins] reload failed {name}: {e}")
        return False
