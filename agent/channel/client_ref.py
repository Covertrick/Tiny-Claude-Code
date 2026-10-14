"""持有运行中的 OneBotClient，供工具侧发文件等主动 API。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.channel.onebot import OneBotClient

_CLIENT: OneBotClient | None = None


def set_onebot_client(client: OneBotClient | None) -> None:
    global _CLIENT
    _CLIENT = client


def get_onebot_client() -> OneBotClient | None:
    return _CLIENT
