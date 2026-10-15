"""OneBot v11 WebSocket 客户端（正向 WS，对接 NapCat / LLOneBot）。"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

from agent.channel.lifecycle import is_shutting_down
from agent.config import ONEBOT_ACCESS_TOKEN, ONEBOT_WS_URL


class OneBotClient:
    def __init__(
        self,
        ws_url: str | None = None,
        access_token: str | None = None,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.ws_url = ws_url or ONEBOT_WS_URL
        self.access_token = access_token if access_token is not None else ONEBOT_ACCESS_TOKEN
        self.on_event = on_event
        self._ws = None
        self._echo_waiters: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._running = False
        self.self_id: str | None = None
        self.last_connected_at: float = 0.0
        self.connected: bool = False

    def _headers(self) -> list[tuple[str, str]]:
        if not self.access_token:
            return []
        return [("Authorization", f"Bearer {self.access_token}")]

    def connect(self) -> None:
        import websocket

        url = self.ws_url
        if self.access_token and "access_token=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}access_token={self.access_token}"

        self._running = True

        def _on_message(_ws, message: str) -> None:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                return
            echo = data.get("echo")
            if echo and echo in self._echo_waiters:
                with self._lock:
                    waiter = self._echo_waiters.pop(echo, None)
                if waiter is not None:
                    waiter["result"] = data
                    waiter["event"].set()
                return
            if data.get("post_type") == "meta_event" and data.get("meta_event_type") == "lifecycle":
                self.self_id = str(data.get("self_id") or self.self_id or "")
            if self.on_event:
                try:
                    self.on_event(data)
                except Exception as e:
                    print(f"[onebot] 事件处理失败: {e}")

        def _on_error(_ws, error) -> None:
            print(f"[onebot] WS error: {error}")

        def _on_close(_ws, status_code, msg) -> None:
            self.connected = False
            print(f"[onebot] WS closed: {status_code} {msg}")

        def _on_open(_ws) -> None:
            self.connected = True
            self.last_connected_at = time.time()
            print(f"[onebot] 已连接 {self.ws_url}")

        self._ws = websocket.WebSocketApp(
            url,
            header=[f"{k}: {v}" for k, v in self._headers()],
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
            on_open=_on_open,
        )

        def _run() -> None:
            while self._running and not is_shutting_down():
                try:
                    self._ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    print(f"[onebot] run_forever 异常: {e}")
                if not self._running or is_shutting_down():
                    break
                print("[onebot] 5 秒后重连…")
                time.sleep(5)

        threading.Thread(target=_run, name="onebot-ws", daemon=True).start()

    def close(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    def call_api(self, action: str, params: dict | None = None, timeout: float = 15.0) -> dict:
        if self._ws is None:
            raise RuntimeError("WebSocket 未连接")
        echo = uuid.uuid4().hex
        payload = {"action": action, "params": params or {}, "echo": echo}
        event = threading.Event()
        waiter: dict[str, Any] = {"event": event, "result": None}
        with self._lock:
            self._echo_waiters[echo] = waiter
        self._ws.send(json.dumps(payload, ensure_ascii=False))
        if not event.wait(timeout):
            with self._lock:
                self._echo_waiters.pop(echo, None)
            raise TimeoutError(f"OneBot API 超时: {action}")
        data = waiter["result"] or {}
        if data.get("status") == "failed":
            raise RuntimeError(f"OneBot API 失败: {data}")
        return data.get("data") if "data" in data else data

    def send_group_msg(self, group_id: int | str, message: str | list) -> dict:
        return self.call_api(
            "send_group_msg",
            {"group_id": int(group_id), "message": message},
        )

    def send_private_msg(self, user_id: int | str, message: str | list) -> dict:
        return self.call_api(
            "send_private_msg",
            {"user_id": int(user_id), "message": message},
        )

    def get_login_info(self) -> dict:
        return self.call_api("get_login_info")

    def upload_private_file(self, user_id: int | str, path: str, name: str) -> dict:
        return self.call_api(
            "upload_private_file",
            {"user_id": int(user_id), "file": path, "name": name},
        )

    def upload_group_file(
        self, group_id: int | str, path: str, name: str
    ) -> dict:
        return self.call_api(
            "upload_group_file",
            {"group_id": int(group_id), "file": path, "name": name},
        )
