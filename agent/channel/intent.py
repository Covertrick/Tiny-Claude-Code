"""意图门控：模型分类是否注入记忆 / 待办预览。

默认走一次极短 chat/completions；失败或 QQ_INTENT_GATE=regex 时回退正则。
宁可漏召回，也不要闲聊误召回。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

# —— 正则回退（LLM 失败 / 显式 regex 模式）——
_RECALL_INTENT_RE = re.compile(
    r"(记得|记不记得|还记得|想起|回忆|之前|上次|从前|那次|那会儿|"
    r"找一下|找找|帮我找|查一下|查查|搜索|搜一下|"
    r"列出|列举|罗列|有哪些|有什么文件|全部文件|"
    r"发出来|发给我|发我|调出来|拿出|翻出来|"
    r"那个文件|那张图|那张|表情包|附件|"
    r"知识卡片|归纳一下|我的偏好|你还记得我|"
    r"我喜欢什么|我叫什么|我是谁)",
    re.I,
)
_SCHEDULE_INTENT_RE = re.compile(
    r"(提醒|催办|待办|日程|行程|任务|到点|还有多久|几点|"
    r"记得叫我|别忘了|闹钟|开会|考试|ddl|deadline)",
    re.I,
)
_BOT_NAME_RE = re.compile(
    r"^(大肥鱼|鲸鱼娘|小鲸鱼|肥鱼)(鲸鱼娘)?[，,\s　]*",
    re.I,
)

_CLASSIFY_SYS = """你是 QQ 机器人的意图分类器。判断用户这句话是否需要向模型注入：
1) memory：长期记忆/文件回忆上下文
2) schedule：待办/催办预览

只输出一行 JSON，不要 Markdown，不要解释：
{"memory":false,"schedule":false}

判定规则（宁可 false，不要误开）：
- memory=true：明确要找/查/发/列出文件或旧内容；回忆「之前/上次」；问你是否记得某偏好/名字
- memory=false：闲聊、问候、关心身体/心情、问你是什么模型、当前话题讨论、贴链接总结分析（除非要对照旧记忆）
- schedule=true：催办、待办、日程、提醒、还有多久、开会/考试时间
- schedule=false：其它
"""


@dataclass(frozen=True)
class IntentGate:
    memory: bool = False
    schedule: bool = False
    source: str = "default"  # llm | regex | off | empty


def intent_gate_mode() -> str:
    """llm（默认）| regex | off。"""
    return (os.getenv("QQ_INTENT_GATE") or "llm").strip().lower()


def strip_bot_address(text: str) -> str:
    t = (text or "").strip()
    t = _BOT_NAME_RE.sub("", t).strip()
    return t


def recall_query(text: str) -> str:
    """去掉口头称呼，避免昵称本身撞上『大肥鱼xxx』类记忆。"""
    t = strip_bot_address(text)
    return (t[:200] if t else (text or "")[:200])


def _regex_gate(text: str) -> IntentGate:
    t = (text or "").strip()
    return IntentGate(
        memory=bool(_RECALL_INTENT_RE.search(t)),
        schedule=bool(_SCHEDULE_INTENT_RE.search(t)),
        source="regex",
    )


def _parse_gate(raw: str) -> IntentGate | None:
    text = (raw or "").strip()
    if not text:
        return None
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if m:
            text = m.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj: dict[str, Any] = json.loads(m.group(0))
    except Exception:
        return None

    def _as_bool(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v or "").strip().lower()
        return s in ("1", "true", "yes", "y", "是", "需要")

    return IntentGate(
        memory=_as_bool(obj.get("memory")),
        schedule=_as_bool(obj.get("schedule")),
        source="llm",
    )


def _llm_gate(text: str) -> IntentGate | None:
    try:
        from agent.channel.trust import wrap_untrusted
        from agent.core.llm import chat

        msg = chat(
            [
                {"role": "system", "content": _CLASSIFY_SYS},
                {
                    "role": "user",
                    "content": wrap_untrusted("user_utterance", text[:500], max_len=500),
                },
            ],
            tools=None,
            max_tokens=60,
            timeout=20,
        )
        return _parse_gate(str(msg.get("content") or ""))
    except Exception as e:
        print(f"[intent] LLM 分类失败，回退正则: {e}")
        return None


def classify_intent(text: str) -> IntentGate:
    """返回本轮是否注入记忆 / 待办。"""
    t = (text or "").strip()
    if not t:
        return IntentGate(source="empty")

    mode = intent_gate_mode()
    if mode in ("off", "0", "false", "no"):
        # 关闭门控 = 总是注入（旧行为）
        return IntentGate(memory=True, schedule=True, source="off")
    if mode == "regex":
        return _regex_gate(t)

    # 默认 llm
    hit = _llm_gate(t)
    if hit is not None:
        print(
            f"[intent] llm memory={hit.memory} schedule={hit.schedule} "
            f"text={t[:40]!r}"
        )
        return hit
    fb = _regex_gate(t)
    print(
        f"[intent] regex-fallback memory={fb.memory} schedule={fb.schedule} "
        f"text={t[:40]!r}"
    )
    return fb

