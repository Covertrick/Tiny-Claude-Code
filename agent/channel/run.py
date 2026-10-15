"""QQ 频道 → core.loop 的绞杀入口。

只注入 tools.qq（无 bash/edit/Task DAG/MCP）。
依赖：channel.run → core.loop ← tools.qq（单向）。
"""

from __future__ import annotations

from agent.channel.context import ChatContext
from agent.channel.prompts import build_system_prompt
from agent.channel.trust import wrap_untrusted
from agent.core.loop import agent_loop
from agent.search import extract_urls, fetch_urls_from_text
from agent.tools.qq import build_tools


def _user_content_with_pages(text: str) -> str:
    """用户话里带链接时预取正文，省一轮工具往返，也避免模型空口编。"""
    text = text or ""
    if not extract_urls(text):
        return text
    print(f"[fetch] 预取链接… {extract_urls(text)}")
    pages = fetch_urls_from_text(text)
    if not pages:
        return text
    block = wrap_untrusted("fetched_pages", pages, max_len=10000)
    return (
        f"{text}\n\n"
        f"（系统已打开上述链接，正文如下；请据此分析/总结，勿编造）\n"
        f"{block}"
    )


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

    user_content = _user_content_with_pages(ctx.text)

    messages: list[dict] = [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_content},
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
