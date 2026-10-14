"""联网搜索：DuckDuckGo HTML 兜底，无额外强依赖。"""

from __future__ import annotations

import json
import re
import urllib.parse

import requests


def web_search(query: str, max_results: int = 5) -> str:
    q = (query or "").strip()
    if not q:
        return "搜索词为空"

    try:
        from duckduckgo_search import DDGS

        results = [
            {
                "title": item.get("title"),
                "href": item.get("href"),
                "body": item.get("body"),
            }
            for item in DDGS().text(q, max_results=max_results)
        ]
        if results:
            return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": q},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        resp.raise_for_status()
        html = resp.text
        titles = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=re.I | re.S,
        )
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
            html,
            flags=re.I | re.S,
        )
        results = []
        for i, (href, title) in enumerate(titles[:max_results]):
            clean_title = urllib.parse.unquote(re.sub(r"<[^>]+>", "", title)).strip()
            body = ""
            if i < len(snippets):
                body = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            m = re.search(r"uddg=([^&]+)", href)
            real = urllib.parse.unquote(m.group(1)) if m else href
            results.append({"title": clean_title, "href": real, "body": body})
        return (
            json.dumps(results, ensure_ascii=False, indent=2)
            if results
            else "未找到相关结果"
        )
    except Exception as e:
        return f"搜索失败: {e}"
