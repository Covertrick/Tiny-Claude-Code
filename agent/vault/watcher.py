"""watchdog 监听 Vault .md 变动，防抖后增量索引。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from agent.config import VAULT_WATCH
from agent.vault.sync import index_file, remove_indexed, vault_root

_observer = None
_debounce: dict[str, float] = {}
_lock = threading.Lock()
_DEBOUNCE_SEC = 1.2


def _schedule(path: str, *, deleted: bool = False) -> None:
    with _lock:
        _debounce[path] = time.time()

    def _flush() -> None:
        time.sleep(_DEBOUNCE_SEC)
        with _lock:
            ts = _debounce.get(path)
            if ts is None or time.time() - ts < _DEBOUNCE_SEC - 0.05:
                return
            _debounce.pop(path, None)
        try:
            if deleted:
                remove_indexed(path)
                print(f"[vault] 已移除索引 {path}")
            else:
                msg = index_file(path)
                print(f"[vault] {msg}")
        except Exception as e:
            print(f"[vault] 增量索引失败: {e}")

    threading.Thread(target=_flush, daemon=True).start()


def start_vault_watcher() -> bool:
    """启动监听；未配置路径 / 未装 watchdog / QQ_VAULT_WATCH=0 则跳过。"""
    global _observer
    if not VAULT_WATCH:
        print("[vault] 监听关闭（QQ_VAULT_WATCH=0）")
        return False
    root = vault_root()
    if root is None:
        print("[vault] 未配置 QQ_VAULT_PATH，跳过监听")
        return False
    if _observer is not None:
        return True
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        print("[vault] 未安装 watchdog，跳过监听（pip install watchdog）")
        return False

    class Handler(FileSystemEventHandler):
        def on_modified(self, event):  # noqa: N802
            if event.is_directory:
                return
            if str(event.src_path).lower().endswith(".md"):
                _schedule(event.src_path)

        def on_created(self, event):  # noqa: N802
            self.on_modified(event)

        def on_deleted(self, event):  # noqa: N802
            if event.is_directory:
                return
            if str(event.src_path).lower().endswith(".md"):
                _schedule(event.src_path, deleted=True)

        def on_moved(self, event):  # noqa: N802
            if getattr(event, "dest_path", None):
                if str(event.dest_path).lower().endswith(".md"):
                    _schedule(event.dest_path)
            if str(event.src_path).lower().endswith(".md"):
                _schedule(event.src_path, deleted=True)

    obs = Observer()
    obs.schedule(Handler(), str(root), recursive=True)
    obs.daemon = True
    obs.start()
    _observer = obs
    print(f"[vault] 正在监听 {root}")
    return True


def stop_vault_watcher() -> None:
    global _observer
    if _observer is None:
        return
    try:
        _observer.stop()
        _observer.join(timeout=3)
    except Exception:
        pass
    _observer = None
