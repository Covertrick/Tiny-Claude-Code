"""轻量结构化日志（JSON 一行），无强制依赖。"""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def slog(event: str, **fields: Any) -> None:
    payload = {
        "ts": time.time(),
        "event": event,
        **{k: v for k, v in fields.items() if v is not None},
    }
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        line = f'{{"event":"{event}","error":"log_encode_failed"}}'
    print(line, file=sys.stderr if fields.get("level") == "error" else sys.stdout)
