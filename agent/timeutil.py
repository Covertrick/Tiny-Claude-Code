"""统一时区：调度与展示强制 Asia/Shanghai，落库用 UTC ISO。"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
TZ_UTC = timezone.utc


def now_shanghai() -> datetime:
    return datetime.now(TZ_SHANGHAI)


def now_utc() -> datetime:
    return datetime.now(TZ_UTC)


def ensure_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # 无时区的本地语义按上海理解
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt.astimezone(TZ_UTC)


def parse_to_utc_iso(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("时间不能为空")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as e:
        raise ValueError(
            f"时间格式无效，请用 ISO8601，例如 2026-10-15T15:00:00+08:00: {value}"
        ) from e
    return ensure_aware_utc(dt).isoformat()


def to_shanghai(dt: datetime) -> datetime:
    return ensure_aware_utc(dt).astimezone(TZ_SHANGHAI)
