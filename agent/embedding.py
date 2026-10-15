"""可替换嵌入底座：优先 fastembed，失败回退哈希向量。

Phase 1：接口统一，便于后续接 sqlite-vec；不强制安装重依赖。
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashEmbedder:
    """零依赖字面量哈希向量（回退）。"""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = re.findall(r"[\u4e00-\u9fff]{1,2}|[a-zA-Z0-9_]+", (text or "").lower())
        if not tokens:
            tokens = [(text or "empty").lower()[:32] or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for i in range(0, min(len(digest), 32), 2):
                idx = int.from_bytes(digest[i : i + 2], "big") % self.dim
                sign = 1.0 if digest[i] % 2 == 0 else -1.0
                vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class FastEmbedEmbedder:
    """可选语义嵌入（需 pip install fastembed）。"""

    def __init__(self, model: str = "BAAI/bge-small-zh-v1.5"):
        from fastembed import TextEmbedding  # type: ignore

        self._model = TextEmbedding(model_name=model)
        # bge-small 多为 384 维
        probe = list(self._model.embed(["ping"]))[0]
        self.dim = len(probe)
        self._lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        with self._lock:
            vec = list(self._model.embed([text or ""]))[0]
        # 已是单位向量或近似；再归一一次
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [float(v) / norm for v in vec]


_EMBEDDER: Embedder | None = None
_LOCK = threading.Lock()
_BACKEND = "hash"


def get_embedder() -> Embedder:
    global _EMBEDDER, _BACKEND
    if _EMBEDDER is not None:
        return _EMBEDDER
    with _LOCK:
        if _EMBEDDER is not None:
            return _EMBEDDER
        try:
            import os

            if os.getenv("QQ_EMBEDDING_BACKEND", "auto").lower() in (
                "fastembed",
                "auto",
            ):
                _EMBEDDER = FastEmbedEmbedder(
                    os.getenv("QQ_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
                )
                _BACKEND = "fastembed"
                print(f"[embed] 使用 fastembed dim={_EMBEDDER.dim}")
                return _EMBEDDER
        except Exception as e:
            print(f"[embed] fastembed 不可用，回退哈希向量: {e}")
        _EMBEDDER = HashEmbedder()
        _BACKEND = "hash"
        print(f"[embed] 使用哈希向量 dim={_EMBEDDER.dim}")
        return _EMBEDDER


def embedding_backend() -> str:
    get_embedder()
    return _BACKEND


def cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(n))
