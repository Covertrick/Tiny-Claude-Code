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
from agent.admin import maybe_start_admin
from agent.bootstrap_napcat import bootstrap
from agent.config import (
    ALERT_KEYWORDS,
    ensure_runtime_dirs,
    sync_napcat_webui_token,
    webui_url,
)
from agent.knowledge.maintenance import register_memory_jobs
from agent.scheduler import ReminderScheduler, set_reminder_scheduler


def main() -> None:
    # 自动补全 .env + 启动 NapCat（若 WS 未开）
    bootstrap(auto_start_napcat=True)
    # 重新读一遍模块里可能已刷新的配置
    from agent import config as cfg

    ensure_runtime_dirs()
    try:
        from agent.core.llm import set_usage_hook
        from agent.observability.usage import record_usage_from_api

        set_usage_hook(record_usage_from_api)
    except Exception as e:
        print(f"[usage] hook 跳过: {e}")
    if not cfg.API_KEY:
        print("缺少 API_KEY，请在 agent/.env 配置 DeepSeek 密钥")
        sys.exit(1)

    webui_token = sync_napcat_webui_token() or cfg.NAPCAT_WEBUI_TOKEN

    print("=" * 50)
    print(" Tiny QQ Agent")
    print(f" 模型: {cfg.MODEL_NAME}")
    print(f" OneBot WS: {cfg.ONEBOT_WS_URL}")
    print(
        f" 机器人 QQ: {cfg.BOT_QQ or cfg.QQ_ACCOUNT or '(连接后自动获取)'}"
    )
    print(
        f" 主人 QQ: {cfg.OWNER_QQ or '(未配置 QQ_OWNER_QQ，早报/关键词告警关闭)'}"
    )
    print(f" 关键词: {', '.join(ALERT_KEYWORDS) or '(无)'}")
    print(f" NapCat WebUI: {webui_url()}")
    if webui_token:
        print(f" WebUI Token: {webui_token}  （已写入 agent/.env）")
    else:
        print(
            " WebUI Token: （尚未生成）等 NapCat 启动后会自动写入 .env，"
            "也可看 docs/qq-setup.md"
        )
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

    client = OneBotClient(ws_url=cfg.ONEBOT_WS_URL, on_event=on_event)
    set_onebot_client(client)
    router = MessageRouter(client)
    client.connect()

    scheduler = ReminderScheduler(client)
    set_reminder_scheduler(scheduler)
    scheduler.start()
    register_morning_brief(scheduler)
    register_memory_jobs(scheduler)
    try:
        from agent.life.monitor import register_digest_job

        register_digest_job(scheduler)
    except Exception as e:
        print(f"[digest] 注册失败: {e}")

    try:
        from plugins.loader import load_all

        load_all()
    except Exception as e:
        print(f"[plugins] 加载跳过: {e}")

    maybe_start_admin()

    # Obsidian Vault：可选全量预扫 + watchdog 监听
    def stop_vault_watcher() -> None:
        return None

    try:
        from agent.vault.sync import reindex_vault, vault_enabled
        from agent.vault.watcher import start_vault_watcher
        from agent.vault.watcher import stop_vault_watcher as _stop_vault_watcher

        stop_vault_watcher = _stop_vault_watcher  # noqa: F811
        if vault_enabled():
            if str(__import__("os").getenv("QQ_VAULT_REINDEX_ON_START", "0")).strip() in (
                "1",
                "true",
                "yes",
            ):
                print("[vault]", reindex_vault())
            start_vault_watcher()
    except Exception as e:
        print(f"[vault] 启动跳过: {e}")

    # 可选：启动时自动打开 WebUI 并填 Token
    if str(__import__("os").getenv("QQ_OPEN_WEBUI", "")).strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        try:
            from agent.webui_login import auto_login_and_open

            auto_login_and_open(open_browser=True)
        except Exception as e:
            print(f"[webui] 自动登录跳过: {e}")

    health = HealthMonitor(client)
    health.start()

    def _cleanup(_reason: str) -> None:
        try:
            stop_vault_watcher()
        except Exception:
            pass
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
