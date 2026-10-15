"""消息处理队列：有界队列 + worker，避免高并发时无限开线程。"""

from __future__ import annotations

import queue
import threading
from typing import Callable

from agent.observability.logging import slog

_QUEUE: queue.Queue | None = None
_STARTED = False
_LOCK = threading.Lock()
_WORKERS = 3


def get_job_queue() -> queue.Queue:
    global _QUEUE, _STARTED
    with _LOCK:
        if _QUEUE is None:
            _QUEUE = queue.Queue(maxsize=200)
        if not _STARTED:
            for i in range(_WORKERS):
                threading.Thread(
                    target=_worker, args=(i,), name=f"qq-job-{i}", daemon=True
                ).start()
            _STARTED = True
            slog("job_queue_started", workers=_WORKERS)
        return _QUEUE


def _worker(idx: int) -> None:
    q = get_job_queue()
    while True:
        fn: Callable[[], None] = q.get()
        try:
            fn()
        except Exception as e:
            slog("job_error", worker=idx, error=str(e), level="error")
        finally:
            q.task_done()


def submit_job(fn: Callable[[], None]) -> bool:
    """提交任务；队列满则返回 False（由调用方提示用户）。"""
    q = get_job_queue()
    try:
        q.put_nowait(fn)
        return True
    except queue.Full:
        slog("job_queue_full", level="error")
        return False
