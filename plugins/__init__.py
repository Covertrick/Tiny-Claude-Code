"""热插拔插件目录（Phase 3）。

每个子包提供：
  manifest.yaml  — name / version / tools / sandbox
  plugin.py      — register(registry) 
"""

from plugins.loader import PluginRegistry, get_registry, load_all, reload_plugin

__all__ = ["PluginRegistry", "get_registry", "load_all", "reload_plugin"]
