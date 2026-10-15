"""持久语义向量索引（sqlite-vec / 纯 SQLite 回退）。"""

from .store import VectorIndex, get_vector_index

__all__ = ["VectorIndex", "get_vector_index"]
