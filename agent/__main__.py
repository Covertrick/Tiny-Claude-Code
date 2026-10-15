"""默认入口：python -m agent  → 启动 QQ Agent。

Coding CLI：python -m agent.main
本地演示：python -m agent.demo
冒烟测试：python -m agent.smoke_test
"""

from __future__ import annotations

import sys
import time

from agent.channel.client_ref import set_onebot_client
from agent.channel.health import HealthMonitor
from agent.channel.lifecycle import is_shutting_down, on_shutdown
from agent.channel.onebot import OneBotClient
from agent.channel.proactive import register_morning_brief
from agent.channel.router import MessageRouter
from agent.config import (
    ALERT_KEYWORDS,
    API_KEY,
    BOT_QQ,
    MODEL_NAME,
    ONEBOT_WS_URL,
    OWNER_QQ,
    QQ_ACCOUNT,
    ensure_runtime_dirs,
)
from agent.scheduler import ReminderScheduler, set_reminder_scheduler


def main() -> None:
    ensure_runtime_dirs()
    if not API_KEY:
        print("缺少 API_KEY，请在 agent/.env 配置 DeepSeek 密钥")
        sys.exit(1)

    print("=" * 50)
    print(" Tiny QQ Agent")
    print(f" 模型: {MODEL_NAME}")
    print(f" OneBot WS: {ONEBOT_WS_URL}")
    print(f" 机器人 QQ: {BOT_QQ or QQ_ACCOUNT or '(连接后自动获取)'}")
    print(f" 主人 QQ: {OWNER_QQ or '(未配置 QQ_OWNER_QQ，早报/关键词告警关闭)'}")
    print(f" 关键词: {', '.join(ALERT_KEYWORDS) or '(无)'}")
    print("=" * 50)
    print(
        "群聊：未@只缓存；「保存上面的文件」可回捞；"
        "文件列表走私聊；异地登录自动退出。Ctrl+C 退出\n"
    )

    router: MessageRouter | None = None
    scheduler: ReminderScheduler | None = None
    health: HealthMonitor | None = None

    def on_event(event: dict) -> None:
        if router:
            router.handle_event(event)

    client = OneBotClient(on_event=on_event)
    set_onebot_client(client)
    router = MessageRouter(client)
    client.connect()

    scheduler = ReminderScheduler(client)
    set_reminder_scheduler(scheduler)
    scheduler.start()
    register_morning_brief(scheduler)

    health = HealthMonitor(client)
    health.start()

    def _cleanup(_reason: str) -> None:
        try:
            if health:
                health.stop()
        except Exception:
            pass
        try:
            if scheduler:
                scheduler.stop()
        except Exception:
            pass
        set_reminder_scheduler(None)
        set_onebot_client(None)
        try:
            client.close()
        except Exception:
            pass

    on_shutdown(_cleanup)

    for _ in range(20):
        time.sleep(0.5)
        if is_shutting_down():
            return
        try:
            info = client.get_login_info()
            qq = str(info.get("user_id") or "")
            if qq:
                router.bot_qq = qq
                print(f"[ready] 已登录 QQ={qq} 昵称={info.get('nickname') or ''}")
                break
        except Exception:
            continue
    else:
        print("[warn] 未拿到登录信息，请检查 NapCat WebSocket")

    try:
        while not is_shutting_down():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在退出…")
        _cleanup("KeyboardInterrupt")



if __name__ == "__main__":
    main()
