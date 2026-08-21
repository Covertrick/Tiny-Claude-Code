import requests

from ..config import API_KEY, END_POINT, MODEL_NAME

# 评测等可选：每次 chat 后收到 usage dict（若 API 返回）
_usage_hook = None


def set_usage_hook(hook) -> None:
    """注册 usage 回调；传 None 取消。"""
    global _usage_hook
    _usage_hook = hook


def chat(
    messages: list,
    tools: list | None = None,
    max_tokens: int = 5000,
    timeout: int = 180,
) -> dict:
    """请求 OpenAI 兼容 chat/completions，返回 choices[0].message。

    tools 为 None 时不带工具 schema；HTTP 错误由 requests 抛出。
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    response = requests.post(END_POINT, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if _usage_hook is not None:
        _usage_hook(data.get("usage") or {})
    return data["choices"][0]["message"]
