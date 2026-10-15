"""联网搜索 + 打开链接读正文。走统一 HTTP 连接池；空结果也返回可回复文案。"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse

from agent.http_client import (
    fetch_proxies,
    get_sync_client,
    http_backend,
    proxy_url,
    sync_get_text,
    sync_post_form,
)

_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.I)


def extract_urls(text: str, *, limit: int = 3) -> list[str]:
    """从用户话里抽出 http(s) 链接（去掉末尾标点）。"""
    found: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(")。．，,.!！？?;；]）'\"")
        if u and u not in found:
            found.append(u)
        if len(found) >= limit:
            break
    return found


def _proxy_hint() -> str:
    if fetch_proxies():
        return ""
    return (
        "（当前无代理。外网超时可在 agent/.env 设 "
        "QQ_FETCH_PROXY=http://127.0.0.1:7890）"
    )


def _empty_search_reply(
    query: str,
    *,
    tried: list[str],
    errors: list[str] | None = None,
) -> str:
    """无结果 / 全失败时仍给模型可转述的中文说明（禁止空串）。"""
    lines = [
        f"【联网搜索】关键词：{query}",
        "状态：未找到相关公开网页" if not errors else "状态：搜索未成功",
        f"已尝试：{' / '.join(tried) if tried else '无'}",
    ]
    if errors:
        lines.append("细节：" + "；".join(errors[:3]))
    hint = _proxy_hint()
    if hint:
        lines.append(hint.strip())
    lines.append(
        "请用人设口语回复用户：说明没搜到或暂时搜不动，"
        "可建议换关键词、开代理，或直接贴链接让我用 fetch_url；"
        "禁止沉默，禁止编造搜索结果。"
    )
    return "\n".join(lines)


def _ddgs_search(query: str, max_results: int) -> list[dict] | None:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return None
    try:
        proxy = proxy_url()
        rows = list(DDGS(proxy=proxy).text(query, max_results=max_results))
        return [
            {
                "title": item.get("title"),
                "href": item.get("href"),
                "body": item.get("body"),
            }
            for item in rows
            if item
        ]
    except Exception:
        return None


def _ddg_html_search(query: str, max_results: int) -> list[dict] | None:
    try:
        status, page = sync_post_form(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            timeout=30.0,
        )
        if status >= 400 or not page:
            return None
        titles = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            page,
            flags=re.I | re.S,
        )
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
            page,
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
        return results
    except Exception:
        return None


def web_search(query: str, max_results: int = 5) -> str:
    """多路搜索；无论成败都返回非空中文/JSON，方便模型回话。"""
    q = (query or "").strip()
    if not q:
        return (
            "【联网搜索】关键词为空\n"
            "请口语请用户补充想搜什么，禁止装作已搜索。"
        )

    tried: list[str] = []
    errors: list[str] = []

    tried.append("duckduckgo-api")
    rows = _ddgs_search(q, max_results)
    if rows:
        return json.dumps(rows, ensure_ascii=False, indent=2)
    if rows is None:
        errors.append("duckduckgo-api 不可用或异常")

    tried.append("duckduckgo-html")
    rows = _ddg_html_search(q, max_results)
    if rows:
        return json.dumps(rows, ensure_ascii=False, indent=2)
    if rows is None:
        errors.append("duckduckgo-html 请求失败")
    else:
        errors.append("各通道均无命中")

    return _empty_search_reply(q, tried=tried, errors=errors)


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    title = ""
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if m:
        title = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    body = raw
    for pat in (
        r"(?is)<article[^>]*>(.*?)</article>",
        r"(?is)<main[^>]*>(.*?)</main>",
    ):
        m2 = re.search(pat, raw)
        if m2 and len(m2.group(1)) > 200:
            body = m2.group(1)
            break
    text = re.sub(r"(?is)<br\s*/?>", "\n", body)
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"(?is)</div>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if title and title.lower() not in text[:200].lower():
        return f"标题：{title}\n\n{text}"
    return text


def _is_reddit(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return "reddit.com" in host or host.endswith("redd.it")


def _reddit_json_url(final_url: str) -> str:
    parsed = urllib.parse.urlparse(final_url)
    path = parsed.path.rstrip("/")
    if path.endswith(".json"):
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, path, "", "raw_json=1", "")
        )
    path = re.sub(r"/comment/[^/]+.*$", "", path)
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, path + ".json", "", "raw_json=1", "")
    )


def _parse_reddit_json(data) -> str:
    if not isinstance(data, list) or not data:
        if isinstance(data, dict):
            data = [data]
        else:
            return ""

    post = None
    try:
        kids = (data[0].get("data") or {}).get("children") or []
        if kids:
            post = kids[0].get("data") or {}
    except Exception:
        post = None
    if not post:
        return ""

    title = (post.get("title") or "").strip()
    sub = (post.get("subreddit_name_prefixed") or post.get("subreddit") or "").strip()
    author = (post.get("author") or "").strip()
    score = post.get("score")
    selftext = (post.get("selftext") or "").strip()
    link = (post.get("url_overridden_by_dest") or post.get("url") or "").strip()
    lines = [
        f"Reddit 帖子{' ' + sub if sub else ''}",
        f"标题：{title}" if title else "",
        f"作者：u/{author}" if author else "",
        f"赞：{score}" if score is not None else "",
    ]
    if selftext and selftext not in ("[removed]", "[deleted]"):
        lines.append("\n正文：\n" + selftext)
    elif link and "reddit.com" not in link:
        lines.append(f"\n外链：{link}")

    comments: list[str] = []
    if len(data) > 1:
        try:
            ckids = (data[1].get("data") or {}).get("children") or []
        except Exception:
            ckids = []
        for c in ckids:
            if (c.get("kind") or "") != "t1":
                continue
            cd = c.get("data") or {}
            body = (cd.get("body") or "").strip()
            if not body or body in ("[removed]", "[deleted]"):
                continue
            cau = cd.get("author") or "?"
            comments.append(f"- u/{cau}: {body[:400]}")
            if len(comments) >= 8:
                break
    if comments:
        lines.append("\n热评：\n" + "\n".join(comments))
    return "\n".join(x for x in lines if x).strip()


def _clip(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _via_jina(url: str, *, max_chars: int) -> str | None:
    jurl = "https://r.jina.ai/" + url
    try:
        status, _final, text = sync_get_text(
            jurl,
            headers={"Accept": "text/plain"},
            timeout=45.0,
        )
        if status >= 400 or len((text or "").strip()) < 40:
            return None
        return _clip(f"来源：{url}\n（via jina）\n\n{text.strip()}", max_chars)
    except Exception:
        return None


def fetch_url(url: str, *, max_chars: int = 8000) -> str:
    """打开链接，抽出可读正文（Reddit → JSON；失败 → Jina；再失败 → HTML）。"""
    u = (url or "").strip()
    if not u:
        return "链接为空。请口语请用户贴一个 http(s) 链接。"
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return "只支持 http/https 链接。请口语说明并请用户换链接。"

    proxy_hint = _proxy_hint()
    last_err = ""

    try:
        if http_backend() == "httpx":
            client = get_sync_client()
            head = client.get(u, timeout=25.0)
            status = head.status_code
            final = str(head.url) or u
            head_text = head.text
            ctype = (head.headers.get("Content-Type") or "").lower()
        else:
            status, final, head_text = sync_get_text(u, timeout=25.0)
            ctype = ""

        if _is_reddit(final) or _is_reddit(u):
            jurl = _reddit_json_url(final)
            try:
                st, _fu, raw = sync_get_text(
                    jurl,
                    headers={"Accept": "application/json"},
                    timeout=25.0,
                )
                if st < 400 and raw:
                    text = _parse_reddit_json(json.loads(raw))
                    if text:
                        return _clip(f"来源：{final}\n\n{text}", max_chars)
            except Exception as e:
                last_err = str(e)

            via = _via_jina(final, max_chars=max_chars)
            if via:
                return via

            if head_text:
                text = _html_to_text(head_text)
                if len(text) >= 40:
                    return _clip(f"来源：{final}\n\n{text}", max_chars)

            return (
                f"打不开这个 Reddit 链接：{final}\n"
                f"{last_err or f'HTTP {status}'}\n"
                f"{proxy_hint}\n"
                f"请口语告诉用户打不开，可请对方粘贴正文让我总结；禁止装作读到了帖子。"
            )

        if "application/json" in ctype or (
            head_text.strip().startswith("{") or head_text.strip().startswith("[")
        ):
            try:
                blob = json.dumps(json.loads(head_text), ensure_ascii=False, indent=2)
            except Exception:
                blob = head_text
            if len(blob.strip()) >= 20:
                return _clip(f"来源：{final}\n\n{blob}", max_chars)

        if status < 400 and len(head_text) >= 40:
            text = _html_to_text(head_text)
            if len(text) >= 40:
                return _clip(f"来源：{final}\n\n{text}", max_chars)

        via = _via_jina(final, max_chars=max_chars)
        if via:
            return via

        return (
            f"打开失败 HTTP {status}：{final}\n"
            f"{proxy_hint}\n"
            f"请口语告诉用户打不开，可请对方粘贴正文；禁止编造页面内容。"
        )
    except Exception as e:
        last_err = str(e)
        via = _via_jina(u, max_chars=max_chars)
        if via:
            return via
        return (
            f"打开链接失败：{last_err}\n"
            f"目标：{u}\n"
            f"{proxy_hint}\n"
            f"请口语告诉用户打不开，可请对方粘贴正文；禁止编造页面内容。"
        )


def fetch_urls_from_text(text: str, *, max_chars_each: int = 6000) -> str:
    """批量打开用户消息里的链接，拼成一块资料。"""
    urls = extract_urls(text)
    if not urls:
        return ""
    parts = []
    for u in urls:
        parts.append(fetch_url(u, max_chars=max_chars_each))
    return "\n\n==========\n\n".join(parts)
