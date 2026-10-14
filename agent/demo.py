"""本地演示：不连 QQ。前缀 g: 群聊 / p: 私聊。走主 agent_loop。"""

from __future__ import annotations

from agent.channel.run import run_qq_agent
from agent.config import ensure_runtime_dirs
from agent.channel.context import ChatContext
from agent.channel.session import SESSIONS, session_key


def main() -> None:
    ensure_runtime_dirs()
    print("QQ Agent 本地演示（agent.core.loop）")
    print("g: 模拟群聊  p: 模拟私聊  exit 退出\n")
    user_id = "1963535087"
    group_id = "10001"
    is_group = False

    while True:
        raw = input(f"[{'group' if is_group else 'private'}] >> ").strip()
        if raw.lower() in ("exit", "quit", ""):
            break
        if raw.startswith("g:"):
            is_group, text = True, raw[2:].strip()
        elif raw.startswith("p:"):
            is_group, text = False, raw[2:].strip()
        else:
            text = raw

        ctx = ChatContext(
            user_id=user_id,
            group_id=group_id if is_group else None,
            is_group=is_group,
            nickname="测试用户",
            text=text,
        )
        skey = session_key(user_id=user_id, group_id=ctx.group_id, is_group=is_group)
        reply = run_qq_agent(ctx=ctx, history=SESSIONS.load(skey))
        SESSIONS.append(skey, "user", text)
        SESSIONS.append(skey, "assistant", reply)
        print(reply, end="\n\n")


if __name__ == "__main__":
    main()
