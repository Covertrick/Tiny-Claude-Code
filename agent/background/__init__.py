"""后台任务：显式 run_in_background 的 bash。"""
from .manager import (
    BACKGROUND,
    inject_background_results,
    should_run_background,
)
__all__ = [
    "BACKGROUND",
    "inject_background_results",
    "should_run_background",
]