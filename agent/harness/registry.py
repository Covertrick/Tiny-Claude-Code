"""自描述 Skill 注册表。

启动只扫描 manifest（yaml/json），不 import。
Run 创建时冻结版本快照并计入引用；引用为 0 才允许卸载。
"""

from __future__ import annotations

import importlib.util
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.RLock()
_REGISTRY: "SkillRegistry | None" = None


def _plugins_root() -> Path:
    return Path(__file__).resolve().parents[2] / "plugins"


def _read_manifest(directory: Path) -> dict | None:
    yaml_path = directory / "manifest.yaml"
    json_path = directory / "manifest.json"
    if yaml_path.is_file():
        try:
            import yaml

            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"[skills] manifest.yaml 读取失败 {directory.name}: {e}")
            return None
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as e:
            print(f"[skills] manifest.json 读取失败 {directory.name}: {e}")
            return None
    return None


@dataclass
class IndexedSkill:
    package: str
    name: str  # 对外工具名
    version: str
    description: str
    effect_class: str
    sandbox_policy: str
    permissions: list[str]
    directory: Path
    status: str = "indexed"  # indexed | loaded | disabled
    module: Any = None

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "effect_class": self.effect_class,
            "permissions": list(self.permissions),
            "sandbox_policy": self.sandbox_policy,
            "source": "plugin",
            "package": self.package,
        }


@dataclass
class ToolAPI:
    """交给插件 register/unregister 的窄接口。"""

    tools: dict[str, Callable[..., str]] = field(default_factory=dict)
    interceptors: list[Callable[..., Any]] = field(default_factory=list)

    def register_tool(self, name: str, handler: Callable[..., str]) -> None:
        self.tools[name] = handler

    def unregister_tool(self, name: str) -> None:
        self.tools.pop(name, None)

    def register_interceptor(self, fn: Callable[..., Any]) -> None:
        self.interceptors.append(fn)

    def clear_owned(self, names: set[str]) -> None:
        for name in list(names):
            self.tools.pop(name, None)


class SkillRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else _plugins_root()
        self.by_tool: dict[str, IndexedSkill] = {}
        self.by_package: dict[str, IndexedSkill] = {}
        self.api = ToolAPI()
        self._refs: dict[tuple[str, str], int] = {}
        self._released_runs: set[str] = set()
        self._pinned: dict[tuple[str, str], Any] = {}

    def scan(self) -> list[str]:
        """只读元数据。"""
        found: list[str] = []
        with _LOCK:
            self.by_tool.clear()
            self.by_package.clear()
            if not self.root.is_dir():
                return found
            for directory in sorted(self.root.iterdir()):
                if not directory.is_dir() or directory.name.startswith("_"):
                    continue
                if directory.name in ("__pycache__",):
                    continue
                meta = _read_manifest(directory)
                if not meta:
                    continue
                package = directory.name
                version = str(meta.get("version") or "0.0.0")
                tools = list(meta.get("tools") or [meta.get("name") or package])
                effect = str(meta.get("effect_class") or "idempotent")
                policy = str(meta.get("sandbox_policy") or "none")
                perms = list(meta.get("permissions") or [])
                desc = str(meta.get("description") or "")
                for tool in tools:
                    entry = IndexedSkill(
                        package=package,
                        name=str(tool),
                        version=version,
                        description=desc,
                        effect_class=effect,
                        sandbox_policy=policy,
                        permissions=perms,
                        directory=directory,
                    )
                    self.by_tool[str(tool)] = entry
                    self.by_package[package] = entry
                found.append(package)
                print(f"[skills] indexed {package} v{version} (not imported)")
        return found

    def snapshot_map(self) -> dict[str, dict]:
        if not self.by_tool and self.root.is_dir():
            self.scan()
        return {name: entry.snapshot() for name, entry in self.by_tool.items()}

    def refs(self, package: str, version: str) -> int:
        return int(self._refs.get((package, version), 0))

    def acquire_snapshot(self, run_id: str, snapshot: dict) -> None:
        seen: set[tuple[str, str]] = set()
        for meta in (snapshot or {}).values():
            if not isinstance(meta, dict) or meta.get("source") != "plugin":
                continue
            key = (str(meta.get("package") or ""), str(meta.get("version") or ""))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            self._refs[key] = self._refs.get(key, 0) + 1
        self._released_runs.discard(run_id)

    def release_snapshot(self, run_id: str, snapshot: dict) -> None:
        if run_id in self._released_runs:
            return
        self._released_runs.add(run_id)
        seen: set[tuple[str, str]] = set()
        for meta in (snapshot or {}).values():
            if not isinstance(meta, dict) or meta.get("source") != "plugin":
                continue
            key = (str(meta.get("package") or ""), str(meta.get("version") or ""))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            self._refs[key] = max(0, self._refs.get(key, 0) - 1)

    def load(self, package: str) -> bool:
        """按需 import。失败只标记 DISABLED，不抛到主进程。"""
        entry = self.by_package.get(package)
        if entry is None:
            print(f"[skills] 未知插件 {package}")
            return False
        if entry.module is not None and entry.status == "loaded":
            return True
        try:
            mod = self._import_module(entry)
            if hasattr(mod, "register"):
                mod.register(self.api)
            entry.module = mod
            entry.status = "loaded"
            self._pinned[(entry.package, entry.version)] = mod
            print(f"[skills] loaded {package} v{entry.version}")
            return True
        except Exception as e:
            entry.status = "disabled"
            entry.module = None
            print(f"[skills] load 失败 {package}，已隔离: {e}")
            return False

    def handler(self, tool_name: str, version: str | None = None) -> Callable[..., str] | None:
        entry = self.by_tool.get(tool_name)
        if entry is None:
            return None
        # 快照版本：优先用创建 Run 时钉住的模块，而不是后来 reload 的新模块
        pinned = None
        if version:
            pinned = self._pinned.get((entry.package, version))
        mod = pinned or entry.module
        if mod is None:
            if not self.load(entry.package):
                return None
            mod = self._pinned.get((entry.package, entry.version)) or entry.module
        if mod is None:
            return None
        fn = self.api.tools.get(tool_name)
        return fn

    def unload(self, package: str) -> bool:
        entry = self.by_package.get(package)
        if entry is None:
            return False
        if self.refs(entry.package, entry.version) > 0:
            print(f"[skills] {package}@{entry.version} 仍被 Run 引用，拒绝卸载")
            return False
        self._unregister(entry)
        entry.module = None
        entry.status = "indexed"
        self._pinned.pop((entry.package, entry.version), None)
        print(f"[skills] unloaded {package}")
        return True

    def reload(self, package: str) -> bool:
        """引用为 0：先反注册再加载。失败则保持旧模块并标 DISABLED 仅当本来就没加载成功。"""
        entry = self.by_package.get(package)
        if entry is None:
            self.scan()
            entry = self.by_package.get(package)
        if entry is None:
            return False
        if self.refs(entry.package, entry.version) > 0:
            print(f"[skills] {package} 有 Run 引用，跳过升级")
            return False
        old_mod = entry.module
        try:
            if old_mod is not None:
                self._unregister(entry)
            mod = self._import_module(entry, fresh=True)
            if hasattr(mod, "register"):
                mod.register(self.api)
            entry.module = mod
            entry.status = "loaded"
            self._pinned[(entry.package, entry.version)] = mod
            return True
        except Exception as e:
            print(f"[skills] reload 失败，保持旧版: {e}")
            if old_mod is not None:
                try:
                    if hasattr(old_mod, "register"):
                        old_mod.register(self.api)
                    entry.module = old_mod
                    entry.status = "loaded"
                    self._pinned[(entry.package, entry.version)] = old_mod
                except Exception as e2:
                    entry.status = "disabled"
                    print(f"[skills] 旧版也无法恢复: {e2}")
            else:
                entry.status = "disabled"
            return False

    def _unregister(self, entry: IndexedSkill) -> None:
        mod = entry.module
        if mod is not None and hasattr(mod, "unregister"):
            try:
                mod.unregister(self.api)
            except Exception as e:
                print(f"[skills] unregister {entry.package}: {e}")
        else:
            self.api.unregister_tool(entry.name)

    def _import_module(self, entry: IndexedSkill, *, fresh: bool = False):
        plugin_py = entry.directory / "plugin.py"
        if not plugin_py.is_file():
            raise FileNotFoundError(plugin_py)
        mod_name = f"plugins_pin.{entry.package}_{entry.version.replace('.', '_')}"
        if fresh:
            mod_name += f"_{id(entry)}"
        spec = importlib.util.spec_from_file_location(mod_name, plugin_py)
        if spec is None or spec.loader is None:
            raise ImportError(mod_name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def get_skill_registry() -> SkillRegistry:
    global _REGISTRY
    with _LOCK:
        if _REGISTRY is None:
            _REGISTRY = SkillRegistry()
            _REGISTRY.scan()
        return _REGISTRY
