"""运维控制面（Phase 3 骨架）。"""

from agent.admin.metrics import snapshot_metrics

__all__ = ["snapshot_metrics", "maybe_start_admin"]


def maybe_start_admin() -> None:
    """若 QQ_ADMIN_PORT>0 则后台起 FastAPI（可选依赖）。"""
    from agent.config import ADMIN_PORT

    if ADMIN_PORT <= 0:
        return
    try:
        from agent.admin.server import start_admin_thread

        start_admin_thread(ADMIN_PORT)
    except Exception as e:
        print(f"[admin] 未启动控制面: {e}")
