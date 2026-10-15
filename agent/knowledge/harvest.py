"""对话后主动提炼：判断是否值得写入长期记忆 / 用户画像。"""

from __future__ import annotations

import json
import re
from typing import Any


_HARVEST_SYS = """你是记忆管家。判断用户这句话是否包含值得长期记住的稳定事实。
只输出 JSON：
{"remember":false,"profile":{},"memory_text":""}
规则：
- 闲聊/问候/临时问题 → remember=false
- 稳定偏好、身份、重要日期、明确「记住」→ remember=true
- profile 可含 display_name / preferences(数组) / important_dates(对象) / notes(数组)
- memory_text：一句话事实（可空）
宁可漏记，不要把废话当记忆。
"""


def maybe_harvest(*, user_id: str, text: str, group_id: str = "private") -> str | None:
    """返回给人看的短回执（通常 None，静默写入）。"""
    t = (text or "").strip()
    if len(t) < 4 or len(t) > 500:
        return None
    # 明显闲聊跳过，省 Token
    if re.fullmatch(
        r".{0,6}(你好|在吗|哈哈|嗯|哦|好的|谢谢|拜拜|身体怎么样).{0,6}", t
    ):
        return None
    try:
        from agent.channel.trust import wrap_untrusted
        from agent.core.llm import chat
        from agent.knowledge.profile import merge_profile_patch
        from agent.knowledge import get_knowledge_store

        msg = chat(
            [
                {"role": "system", "content": _HARVEST_SYS},
                {
                    "role": "user",
                    "content": wrap_untrusted("utterance", t, max_len=600),
                },
            ],
            tools=None,
            max_tokens=200,
            timeout=25,
        )
        raw = str(msg.get("content") or "")
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        obj: dict[str, Any] = json.loads(m.group(0))
        if not obj.get("remember"):
            return None
        profile = obj.get("profile") or {}
        if isinstance(profile, dict) and profile:
            merge_profile_patch(user_id, profile)
        mem = str(obj.get("memory_text") or "").strip()
        if mem:
            get_knowledge_store().remember(
                user_id=user_id,
                group_id=group_id or "private",
                text=mem,
                source="harvest",
                kind="preference" if "偏好" in mem or "喜欢" in mem else "note",
                title="",
                layer="episodic",
            )
        return None
    except Exception as e:
        print(f"[harvest] skip: {e}")
        return None
