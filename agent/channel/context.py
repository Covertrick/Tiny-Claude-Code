"""统一对话上下文：用户 / 群隔离的唯一数据载体。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatContext:
    """一次请求的身份与作用域。

    - 群聊：is_group=True，group_id 有值 → 记忆/文件仅本群
    - 私聊：is_group=False，group_id=None → 记忆可读该用户全部
    """

    user_id: str
    text: str
    is_group: bool
    group_id: str | None = None
    nickname: str = ""
    group_name: str = ""
    group_context: str = ""  # @ 时注入的近期群聊滑动窗口

    @property
    def storage_group_id(self) -> str:
        """落盘用的 group 键：群为群号，私聊为 private。"""
        return str(self.group_id) if self.is_group and self.group_id else "private"

    @property
    def recall_group_id(self) -> str | None:
        """检索过滤：群聊限定本群；私聊不过滤群（返回 None）。"""
        return str(self.group_id) if self.is_group else None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "group_id": self.group_id,
            "is_group": self.is_group,
            "nickname": self.nickname,
            "group_name": self.group_name,
            "text": self.text,
        }
