"""示例插件：注册一个可撤销的定时线程。"""

from __future__ import annotations

import threading

_stop = threading.Event()
_thread: threading.Thread | None = None
ticks: list[int] = []


def _loop() -> None:
    while not _stop.wait(0.05):
        ticks.append(1)


def register(registry) -> None:
    global _thread
    _stop.clear()
    ticks.clear()
    _thread = threading.Thread(target=_loop, name="echo-tick", daemon=True)
    _thread.start()
    registry.register_tool("plugin_echo", lambda text="": f"echo:{text}")


def unregister(registry) -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=0.4)
        _thread = None
    registry.unregister_tool("plugin_echo")
