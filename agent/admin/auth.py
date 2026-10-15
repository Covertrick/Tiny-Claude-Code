"""Magic Link：按用户 QQ 签发；优先公网隧道 URL，其次局域网。"""

from __future__ import annotations

import hashlib
import socket
from typing import Any
from urllib.parse import urlparse

from agent.config import (
    ADMIN_MAGIC_TTL,
    ADMIN_PORT,
    ADMIN_PUBLIC_HOST,
    ADMIN_PUBLIC_URL,
    ADMIN_SECRET,
    API_KEY,
)


def _secret() -> str:
    raw = ADMIN_SECRET or API_KEY or "tiny-qq-agent-dev"
    return hashlib.sha256(f"admin-magic:{raw}".encode()).hexdigest()


def _serializer():
    try:
        from itsdangerous import URLSafeTimedSerializer
    except ImportError as e:
        raise RuntimeError("需要 itsdangerous（通常随 starlette/fastapi 安装）") from e
    return URLSafeTimedSerializer(_secret(), salt="qq-admin-magic")


def detect_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def public_host() -> str:
    raw = (ADMIN_PUBLIC_HOST or "auto").strip()
    if not raw or raw.lower() in ("auto", "lan", "0.0.0.0"):
        return detect_lan_ip()
    return raw


def public_base_url(*, port: int | None = None) -> str:
    """Magic Link 基址：预设 URL > 隧道运行时 URL > http://局域网:port。"""
    port = ADMIN_PORT if port is None else port
    if ADMIN_PUBLIC_URL:
        return ADMIN_PUBLIC_URL.rstrip("/")
    try:
        from agent.admin.tunnel import get_public_base_url

        tun = get_public_base_url()
        if tun:
            return tun.rstrip("/")
    except Exception:
        pass
    return f"http://{public_host()}:{port}"


def issue_magic_token(*, user_qq: str) -> str:
    qq = str(user_qq or "").strip()
    if not qq:
        raise ValueError("缺少用户 QQ")
    return _serializer().dumps({"qq": qq, "role": "user"})


def verify_magic_token(token: str, *, max_age: int | None = None) -> dict[str, Any]:
    max_age = ADMIN_MAGIC_TTL if max_age is None else max_age
    data = _serializer().loads(token, max_age=max_age)
    if not isinstance(data, dict):
        raise ValueError("token 无效")
    qq = str(data.get("qq") or "").strip()
    if not qq:
        raise ValueError("token 无用户身份")
    return {"qq": qq, "role": str(data.get("role") or "user")}


def magic_link_url(token: str, *, port: int, host: str | None = None) -> str:
    if host:
        return f"http://{host}:{port}/dash?token={token}"
    base = public_base_url(port=port)
    return f"{base}/dash?token={token}"


def build_magic_link(*, user_qq: str, port: int) -> str:
    token = issue_magic_token(user_qq=user_qq)
    return magic_link_url(token, port=port)


def cookie_secure_for_base() -> bool:
    base = public_base_url()
    return urlparse(base).scheme == "https"


def build_owner_magic_link(*, port: int, user_qq: str = "") -> str:
    from agent.config import OWNER_QQ

    return build_magic_link(user_qq=user_qq or OWNER_QQ, port=port)
