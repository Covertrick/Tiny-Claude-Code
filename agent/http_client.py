"""HTTP 连接池：httpx AsyncClient（常驻事件循环）+ 同步桥接 + 代理。

LLM / 联网搜索 / 抓取共用，减少握手与重复 Session。
"""

from __future__ import annotations

import asyncio
import atexit
import os
import threading
from typing import Any

_LOOP: asyncio.AbstractEventLoop | None = None
_THREAD: threading.Thread | None = None
_ASYNC_CLIENT = None  # httpx.AsyncClient | None
_SYNC_CLIENT = None  # httpx.Client | None
_LOCK = threading.Lock()
_HTTPX_OK = False
_UA = (
    "Mozilla/5.0 (compatible; TinyQQAgent/1.0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

try:
    import httpx

    _HTTPX_OK = True
except ImportError:
    httpx = None  # type: ignore


def fetch_proxies() -> dict[str, str] | None:
    """外网代理：QQ_FETCH_PROXY > HTTPS_PROXY > HTTP_PROXY。"""
    raw = (
        os.getenv("QQ_FETCH_PROXY")
        or os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
        or ""
    ).strip()
    if not raw:
        return None
    return {"http://": raw, "https://": raw}


def proxy_url() -> str | None:
    p = fetch_proxies()
    if not p:
        return None
    return p.get("https://") or p.get("http://")


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _LOOP, _THREAD
    with _LOCK:
        if _LOOP is not None and _LOOP.is_running():
            return _LOOP
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run, name="httpx-loop", daemon=True)
        t.start()
        _LOOP = loop
        _THREAD = t
        return loop


def get_async_client():
    """懒创建全局 AsyncClient（连接池）。"""
    global _ASYNC_CLIENT
    if not _HTTPX_OK:
        raise RuntimeError("请 pip install httpx")
    with _LOCK:
        if _ASYNC_CLIENT is None:
            _ensure_loop()
            kwargs: dict[str, Any] = dict(
                limits=httpx.Limits(
                    max_connections=32,
                    max_keepalive_connections=16,
                    keepalive_expiry=30.0,
                ),
                timeout=httpx.Timeout(180.0, connect=15.0),
                headers={"User-Agent": _UA},
                follow_redirects=True,
            )
            proxies = fetch_proxies()
            if proxies:
                # httpx 0.28+ 用 proxy=；旧版用 proxies=
                try:
                    _ASYNC_CLIENT = httpx.AsyncClient(proxy=proxy_url(), **kwargs)
                except TypeError:
                    _ASYNC_CLIENT = httpx.AsyncClient(proxies=proxies, **kwargs)
            else:
                _ASYNC_CLIENT = httpx.AsyncClient(**kwargs)
        return _ASYNC_CLIENT


def get_sync_client():
    """同步 Client（连接池），搜索/抓取用。"""
    global _SYNC_CLIENT
    if not _HTTPX_OK:
        raise RuntimeError("请 pip install httpx")
    with _LOCK:
        if _SYNC_CLIENT is None:
            kwargs: dict[str, Any] = dict(
                limits=httpx.Limits(
                    max_connections=32,
                    max_keepalive_connections=16,
                    keepalive_expiry=30.0,
                ),
                timeout=httpx.Timeout(90.0, connect=15.0),
                headers={
                    "User-Agent": _UA,
                    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
            )
            proxies = fetch_proxies()
            if proxies:
                try:
                    _SYNC_CLIENT = httpx.Client(proxy=proxy_url(), **kwargs)
                except TypeError:
                    _SYNC_CLIENT = httpx.Client(proxies=proxies, **kwargs)
            else:
                _SYNC_CLIENT = httpx.Client(**kwargs)
        return _SYNC_CLIENT


def run_coro(coro, *, timeout: float | None = 180.0) -> Any:
    """在常驻事件循环上跑协程（线程安全）。"""
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


async def async_post_json(
    url: str,
    *,
    json_body: dict,
    headers: dict | None = None,
    timeout: float = 180.0,
) -> dict:
    client = get_async_client()
    resp = await client.post(
        url,
        json=json_body,
        headers=headers or {},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


async def async_get_bytes(url: str, *, timeout: float = 90.0) -> bytes:
    client = get_async_client()
    resp = await client.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def sync_post_json(
    url: str,
    *,
    json_body: dict,
    headers: dict | None = None,
    timeout: float = 180.0,
) -> dict:
    """优先走异步池；无 httpx 时回退 requests。"""
    if _HTTPX_OK:
        return run_coro(
            async_post_json(url, json_body=json_body, headers=headers, timeout=timeout),
            timeout=timeout + 5,
        )
    import requests

    r = requests.post(url, json=json_body, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def sync_get_bytes(url: str, *, timeout: float = 90.0) -> bytes:
    if _HTTPX_OK:
        return run_coro(async_get_bytes(url, timeout=timeout), timeout=timeout + 5)
    import requests

    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def sync_get_text(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 45.0,
) -> tuple[int, str, str]:
    """返回 (status_code, final_url, text)。"""
    if _HTTPX_OK:
        client = get_sync_client()
        resp = client.get(url, headers=headers or {}, timeout=timeout)
        return resp.status_code, str(resp.url), resp.text
    import requests

    proxies = None
    raw = proxy_url()
    if raw:
        proxies = {"http": raw, "https": raw}
    r = requests.get(
        url,
        headers={**(headers or {}), "User-Agent": _UA},
        timeout=timeout,
        proxies=proxies,
        allow_redirects=True,
    )
    return r.status_code, str(r.url), r.text


def sync_post_form(
    url: str,
    *,
    data: dict,
    headers: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, str]:
    """表单 POST，返回 (status_code, text)。"""
    if _HTTPX_OK:
        client = get_sync_client()
        resp = client.post(url, data=data, headers=headers or {}, timeout=timeout)
        return resp.status_code, resp.text
    import requests

    proxies = None
    raw = proxy_url()
    if raw:
        proxies = {"http": raw, "https": raw}
    r = requests.post(
        url,
        data=data,
        headers={**(headers or {}), "User-Agent": _UA},
        timeout=timeout,
        proxies=proxies,
    )
    return r.status_code, r.text


def close_http_clients() -> None:
    global _ASYNC_CLIENT, _SYNC_CLIENT, _LOOP
    with _LOCK:
        if _SYNC_CLIENT is not None:
            try:
                _SYNC_CLIENT.close()
            except Exception:
                pass
            _SYNC_CLIENT = None
        client = _ASYNC_CLIENT
        _ASYNC_CLIENT = None
        loop = _LOOP
    if client is not None and loop is not None and loop.is_running():
        try:
            fut = asyncio.run_coroutine_threadsafe(client.aclose(), loop)
            fut.result(timeout=5)
        except Exception:
            pass


atexit.register(close_http_clients)


def http_backend() -> str:
    return "httpx" if _HTTPX_OK else "requests"
