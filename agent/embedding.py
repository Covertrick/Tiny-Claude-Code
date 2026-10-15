"""可替换嵌入底座：默认强制语义（fastembed），失败按 FORCE_SEMANTIC 策略回退。"""

from __future__ import annotations

import hashlib
import math
import os
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
    """语义嵌入（需 pip install fastembed）。"""

    def __init__(self, model: str = "BAAI/bge-small-zh-v1.5"):
        from fastembed import TextEmbedding  # type: ignore

        self._model = TextEmbedding(model_name=model)
        probe = list(self._model.embed(["ping"]))[0]
        self.dim = len(probe)
        self._lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        with self._lock:
            vec = list(self._model.embed([text or ""]))[0]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [float(v) / norm for v in vec]


_EMBEDDER: Embedder | None = None
_LOCK = threading.Lock()
_BACKEND = "hash"


def _force_mode() -> str:
    from agent.config import FORCE_SEMANTIC

    v = (FORCE_SEMANTIC or "1").strip().lower()
    if v in ("0", "false", "off", "no"):
        return "off"
    if v in ("strict", "require", "2"):
        return "strict"
    return "on"


def get_embedder() -> Embedder:
    global _EMBEDDER, _BACKEND
    if _EMBEDDER is not None:
        return _EMBEDDER
    with _LOCK:
        if _EMBEDDER is not None:
            return _EMBEDDER
        backend_pref = os.getenv("QQ_EMBEDDING_BACKEND", "auto").lower()
        force = _force_mode()
        # 显式 hash 永远跳过语义模型（冒烟/离线）；其余按 FORCE_SEMANTIC / auto
        if backend_pref == "hash":
            want_semantic = False
        elif backend_pref == "fastembed" or force != "off":
            want_semantic = True
        else:
            want_semantic = backend_pref == "auto"

        if want_semantic:
            # 避免 HF 超时重试拖死启动（无本地缓存时尤甚）
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "12")
            os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "12")
            model = os.getenv("QQ_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
            load_timeout = float(os.getenv("QQ_EMBEDDING_LOAD_TIMEOUT", "25") or "25")
            holder: list = []

            def _load() -> None:
                try:
                    holder.append(("ok", FastEmbedEmbedder(model)))
                except Exception as e:  # noqa: BLE001
                    holder.append(("err", e))

            t = threading.Thread(target=_load, name="fastembed-load", daemon=True)
            t.start()
            t.join(load_timeout)
            if t.is_alive():
                print(
                    f"[embed] fastembed 加载超过 {load_timeout:.0f}s（常为 HF 下载超时），"
                    "回退哈希；有镜像可设 HF_ENDPOINT 后重启"
                )
            elif holder and holder[0][0] == "ok":
                _EMBEDDER = holder[0][1]
                _BACKEND = "fastembed"
                print(f"[embed] 强制语义索引 fastembed dim={_EMBEDDER.dim}")
                return _EMBEDDER
            else:
                err = holder[0][1] if holder else RuntimeError("unknown")
                msg = f"[embed] fastembed 不可用: {err}"
                if force == "strict" and backend_pref != "hash":
                    raise RuntimeError(
                        "QQ_FORCE_SEMANTIC=strict 但 fastembed 加载失败；"
                        "请 pip install fastembed、确保能下模型，或改 QQ_FORCE_SEMANTIC=1"
                    ) from err
                print(f"{msg} → 回退哈希向量（召回质量会下降）")

        _EMBEDDER = HashEmbedder()
        _BACKEND = "hash"
        print(f"[embed] 使用哈希向量 dim={_EMBEDDER.dim}")
        return _EMBEDDER


def embedding_backend() -> str:
    get_embedder()
    return _BACKEND


def reset_embedder() -> None:
    """测试用：清空单例，下次 get_embedder 按当前环境变量重建。"""
    global _EMBEDDER, _BACKEND
    with _LOCK:
        _EMBEDDER = None
        _BACKEND = "hash"


def cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(n))
