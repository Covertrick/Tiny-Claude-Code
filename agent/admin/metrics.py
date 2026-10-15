"""运行指标快照。"""

from __future__ import annotations

import os
import time
from typing import Any


def snapshot_metrics() -> dict[str, Any]:
    from agent.channel.rate_limit import get_send_breaker, get_send_bucket
    from agent.embedding import embedding_backend
    from agent.knowledge import get_knowledge_store

    bucket = get_send_bucket()
    breaker = get_send_breaker()
    store = get_knowledge_store()
    with store._lock:
        total = len(store._records)
        archived = sum(1 for r in store._records if r.archived)
        semantic = sum(1 for r in store._records if r.layer == "semantic")
    vault_stats = {}
    try:
        from agent.vault.index import get_vault_index
        from agent.vault.sync import vault_enabled

        if vault_enabled():
            vault_stats = get_vault_index().stats()
    except Exception:
        vault_stats = {}

    usage = {}
    try:
        from agent.observability.usage import get_usage_store

        usage = get_usage_store().summary()
    except Exception:
        usage = {}

    return {
        "ts": time.time(),
        "pid": os.getpid(),
        "embedding": embedding_backend(),
        "memory": {
            "total": total,
            "archived": archived,
            "semantic": semantic,
        },
        "vault": vault_stats,
        "usage": usage,
        "send": {
            "breaker_open_remaining": breaker.remaining(),
            "bucket_tokens": round(bucket._tokens, 2),
        },
    }
