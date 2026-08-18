import requests

from ..config import API_KEY, END_POINT, MODEL_NAME


def chat(
    messages: list,
    tools: list | None = None,
    max_tokens: int = 5000,
    timeout: int = 180,
) -> dict:
    """调用 OpenAI 兼容 chat/completions，返回 assistant message。"""
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
    return response.json()["choices"][0]["message"]
