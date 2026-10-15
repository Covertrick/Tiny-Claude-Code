"""WebSocket 健康检查 + 掉线告警（Server 酱 / SMTP / 私聊主人）。"""

from __future__ import annotations

import smtplib
import threading
import time
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any

from agent.config import (
    ALERT_SMTP_HOST,
    ALERT_SMTP_PASS,
    ALERT_SMTP_PORT,
    ALERT_SMTP_TO,
    ALERT_SMTP_USER,
    HEALTH_CHECK_SECONDS,
    HEALTH_DISCONNECT_ALERT_SECONDS,
    OWNER_QQ,
    SERVERCHAN_SENDKEY,
)

if TYPE_CHECKING:
    from agent.channel.onebot import OneBotClient


class HealthMonitor:
    def __init__(self, client: OneBotClient):
        self.client = client
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._alerted = False
        self._last_ok = time.time()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ws-health", daemon=True
        )
        self._thread.start()
        print(
            f"[health] 每 {HEALTH_CHECK_SECONDS}s 检查 WS；"
            f"断线 ≥{HEALTH_DISCONNECT_ALERT_SECONDS}s 告警"
        )

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(HEALTH_CHECK_SECONDS):
            try:
                ok = self._probe()
            except Exception as e:
                print(f"[health] probe 异常: {e}")
                ok = False
            if ok:
                self._last_ok = time.time()
                if self._alerted:
                    self._alerted = False
                    self._notify("QQ Agent 已恢复", "OneBot WebSocket 重新连通")
                continue
            disconnected = time.time() - self._last_ok
            if (
                disconnected >= HEALTH_DISCONNECT_ALERT_SECONDS
                and not self._alerted
            ):
                self._alerted = True
                self._notify(
                    "QQ Agent 掉线告警",
                    f"OneBot WS 已超过 {int(disconnected)} 秒未连通："
                    f"{getattr(self.client, 'ws_url', '')}",
                )

    def _probe(self) -> bool:
        if not getattr(self.client, "_running", False):
            return False
        if not getattr(self.client, "connected", False):
            return False
        ws = getattr(self.client, "_ws", None)
        if ws is None or getattr(ws, "sock", None) is None:
            return False
        try:
            self.client.get_login_info()
            return True
        except Exception as e:
            # 鉴权失败 → 热更新 Token / Access Token，不硬重启进程
            if self._is_auth_error(e):
                self._hot_reload_credentials()
            return False

    @staticmethod
    def _is_auth_error(err: Exception) -> bool:
        text = str(err).lower()
        return any(
            k in text
            for k in (
                "401",
                "403",
                "unauthorized",
                "forbidden",
                "token",
                "鉴权",
                "access_token",
                "认证",
            )
        )

    def _hot_reload_credentials(self) -> None:
        """重读 webui.json / .env，刷新内存中的 Token。"""
        try:
            from agent.bootstrap_napcat import fill_env_from_napcat, reload_agent_config
            from agent.config import NAPCAT_WEBUI_TOKEN, ONEBOT_ACCESS_TOKEN

            fill_env_from_napcat()
            reload_agent_config()
            # OneBot 客户端内存字段
            if hasattr(self.client, "access_token"):
                self.client.access_token = ONEBOT_ACCESS_TOKEN
            print(
                f"[health] 凭证热更新：webui_token="
                f"{(NAPCAT_WEBUI_TOKEN or '')[:6]}… "
                f"onebot_token={'有' if ONEBOT_ACCESS_TOKEN else '无'}"
            )
        except Exception as e:
            print(f"[health] 凭证热更新失败: {e}")

    def _notify(self, title: str, body: str) -> None:
        print(f"[health] ALERT {title}: {body}")
        sent = False
        if SERVERCHAN_SENDKEY:
            try:
                self._serverchan(title, body)
                sent = True
            except Exception as e:
                print(f"[health] Server酱失败: {e}")
        if ALERT_SMTP_HOST and ALERT_SMTP_TO:
            try:
                self._smtp(title, body)
                sent = True
            except Exception as e:
                print(f"[health] SMTP 失败: {e}")
        if OWNER_QQ:
            try:
                from agent.channel.send import safe_send_msg

                safe_send_msg(
                    self.client,
                    user_id=OWNER_QQ,
                    message=f"【{title}】\n{body}",
                    chunk=False,
                )
                sent = True
            except Exception as e:
                print(f"[health] 私聊告警失败: {e}")
        if not sent:
            print("[health] 无可用告警通道（配置 SERVERCHAN_SENDKEY / SMTP / QQ_OWNER_QQ）")

    @staticmethod
    def _serverchan(title: str, body: str) -> None:
        key = SERVERCHAN_SENDKEY
        url = f"https://sctapi.ftqq.com/{key}.send"
        data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()

    @staticmethod
    def _smtp(title: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = ALERT_SMTP_USER
        msg["To"] = ALERT_SMTP_TO
        with smtplib.SMTP_SSL(ALERT_SMTP_HOST, ALERT_SMTP_PORT, timeout=20) as s:
            if ALERT_SMTP_USER:
                s.login(ALERT_SMTP_USER, ALERT_SMTP_PASS)
            s.sendmail(ALERT_SMTP_USER, [ALERT_SMTP_TO], msg.as_string())


def fire_external_alert(title: str, body: str, client: Any | None = None) -> None:
    """供其它模块复用的轻量告警。"""
    mon = HealthMonitor(client) if client else None
    if mon:
        mon._notify(title, body)
