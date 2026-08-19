"""上下文压缩：COMPACTOR 单例与溢出判断。"""

from .compactor import COMPACTOR, MAX_REACTIVE_RETRIES, is_context_overflow

__all__ = ["COMPACTOR", "MAX_REACTIVE_RETRIES", "is_context_overflow"]
