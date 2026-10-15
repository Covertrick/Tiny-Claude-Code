"""LLM 调用：默认走 httpx 异步连接池；提供 chat / chat_async。"""

from __future__ import annotations

from ..config import API_KEY, END_POINT, MODEL_NAME
from ..http_client import async_post_json, http_backend, run_coro, sync_post_json

# 评测等可选：每次 chat 后收到 usage dict（若 API 返回）
_usage_hook = None


def set_usage_hook(hook) -> None:
    """注册 usage 回调；传 None 取消。"""
    global _usage_hook
    _usage_hook = hook


def _payload(
    messages: list,
    tools: list | None,
    max_tokens: int,
) -> dict:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _apply_usage(data: dict) -> None:
    if _usage_hook is not None:
        _usage_hook(data.get("usage") or {})


async def chat_async(
    messages: list,
    tools: list | None = None,
    max_tokens: int = 5000,
    timeout: int = 180,
) -> dict:
    """异步 chat/completions，复用全局 AsyncClient 连接池。"""
    if not END_POINT:
        raise RuntimeError("未配置 BASE_URL / END_POINT")
    data = await async_post_json(
        END_POINT,
        json_body=_payload(messages, tools, max_tokens),
        headers=_headers(),
        timeout=float(timeout),
    )
    _apply_usage(data)
    return data["choices"][0]["message"]


def chat(
    messages: list,
    tools: list | None = None,
    max_tokens: int = 5000,
    timeout: int = 180,
) -> dict:
    """同步入口：在常驻事件循环上调度 chat_async（连接池仍生效）。"""
    if http_backend() == "httpx":
        return run_coro(
            chat_async(messages, tools=tools, max_tokens=max_tokens, timeout=timeout),
            timeout=float(timeout) + 10,
        )
    # 极端无 httpx：直连
    data = sync_post_json(
        END_POINT,
        json_body=_payload(messages, tools, max_tokens),
        headers=_headers(),
        timeout=float(timeout),
    )
    _apply_usage(data)
    return data["choices"][0]["message"]
