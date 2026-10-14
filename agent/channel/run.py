"""QQ 频道 → core.loop 的绞杀入口。

只注入 tools.qq（无 bash/edit/Task DAG/MCP）。
依赖：channel.run → core.loop ← tools.qq（单向）。
"""

from __future__ import annotations

from agent.channel.context import ChatContext
from agent.channel.prompts import build_system_prompt
from agent.core.loop import agent_loop
from agent.tools.qq import build_tools


def run_qq_agent(
    *,
    ctx: ChatContext,
    history: list[dict],
    max_rounds: int = 6,
) -> str:
    """用主 agent_loop 处理一条 QQ 消息，返回最终回复文本。"""
    tools, handlers = build_tools(ctx)
    system = build_system_prompt(ctx)

    def system_provider(_messages: list) -> str:
        return system

    messages: list[dict] = [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": ctx.text},
    ]

    reply = agent_loop(
        messages,
        active_request=ctx.text,
        tools=tools,
        handlers=handlers,
        system_provider=system_provider,
        use_mcp=False,
        extract_memory=False,  # QQ 长期记忆走 save_memory，不用 Coding MEMORY.md
        todo_reminder=False,
        max_rounds=max_rounds,
    )
    return (reply or "").strip() or "（空回复）"
