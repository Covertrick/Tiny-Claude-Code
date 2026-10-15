"""联网搜索 + 打开链接读正文。支持 QQ_FETCH_PROXY；Reddit 优先 JSON，失败再 Jina。"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import urllib.parse

import requests

_UA = (
    "Mozilla/5.0 (compatible; TinyQQAgent/1.0; +https://github.com/local) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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


def _proxies() -> dict[str, str] | None:
    """外网抓取代理：QQ_FETCH_PROXY > HTTPS_PROXY > HTTP_PROXY。"""
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
    return {"http": raw, "https": raw}


def web_search(query: str, max_results: int = 5) -> str:
    q = (query or "").strip()
    if not q:
        return "搜索词为空"
    proxies = _proxies()

    try:
        from duckduckgo_search import DDGS

        results = [
            {
                "title": item.get("title"),
                "href": item.get("href"),
                "body": item.get("body"),
            }
            for item in DDGS(proxy=proxies.get("https") if proxies else None).text(
                q, max_results=max_results
            )
        ]
        if results:
            return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": q},
            headers={"User-Agent": _UA},
            timeout=30,
            proxies=proxies,
        )
        resp.raise_for_status()
        page = resp.text
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
        return (
            json.dumps(results, ensure_ascii=False, indent=2)
            if results
            else "未找到相关结果"
        )
    except Exception as e:
        return f"搜索失败: {e}"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": _UA,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    proxies = _proxies()
    if proxies:
        s.proxies.update(proxies)
    return s


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


def _via_jina(url: str, sess: requests.Session, *, max_chars: int) -> str | None:
    """Jina Reader：把任意 URL 转成纯文本（需能访问 r.jina.ai）。"""
    jurl = "https://r.jina.ai/" + url
    try:
        r = sess.get(
            jurl,
            timeout=45,
            headers={**dict(sess.headers), "Accept": "text/plain"},
        )
        if not r.ok or len(r.text.strip()) < 40:
            return None
        return _clip(f"来源：{url}\n（via jina）\n\n{r.text.strip()}", max_chars)
    except Exception:
        return None


def fetch_url(url: str, *, max_chars: int = 8000) -> str:
    """打开链接，抽出可读正文（Reddit → JSON；失败 → Jina；再失败 → HTML）。"""
    u = (url or "").strip()
    if not u:
        return "链接为空"
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return "只支持 http/https 链接"

    sess = _session()
    proxy_hint = (
        ""
        if _proxies()
        else "（当前无代理。Reddit 等站若超时，可在 agent/.env 设 QQ_FETCH_PROXY=http://127.0.0.1:7890）"
    )
    last_err = ""

    try:
        head = sess.get(u, timeout=25, allow_redirects=True)
        final = head.url or u

        if _is_reddit(final) or _is_reddit(u):
            jurl = _reddit_json_url(final)
            try:
                jr = sess.get(
                    jurl,
                    timeout=25,
                    headers={**dict(sess.headers), "Accept": "application/json"},
                )
                if jr.ok:
                    text = _parse_reddit_json(jr.json())
                    if text:
                        return _clip(f"来源：{final}\n\n{text}", max_chars)
            except Exception as e:
                last_err = str(e)

            via = _via_jina(final, sess, max_chars=max_chars)
            if via:
                return via

            raw = head.text if head.ok else ""
            if raw:
                text = _html_to_text(raw)
                if len(text) >= 40:
                    return _clip(f"来源：{final}\n\n{text}", max_chars)

            return (
                f"打不开这个 Reddit 链接：{final}\n"
                f"{last_err or f'HTTP {head.status_code}'}\n"
                f"{proxy_hint}\n"
                f"也可以直接把帖子正文粘贴过来，我照样总结。"
            )

        ctype = (head.headers.get("Content-Type") or "").lower()
        if "application/json" in ctype:
            try:
                blob = json.dumps(head.json(), ensure_ascii=False, indent=2)
            except Exception:
                blob = head.text
            return _clip(f"来源：{final}\n\n{blob}", max_chars)

        if head.ok and len(head.text) >= 40:
            text = _html_to_text(head.text)
            if len(text) >= 40:
                return _clip(f"来源：{final}\n\n{text}", max_chars)

        via = _via_jina(final, sess, max_chars=max_chars)
        if via:
            return via

        return (
            f"打开失败 HTTP {head.status_code}：{final}\n"
            f"{proxy_hint}\n"
            f"也可以把正文粘贴过来让我总结。"
        )
    except Exception as e:
        last_err = str(e)
        via = _via_jina(u, sess, max_chars=max_chars)
        if via:
            return via
        return (
            f"打开链接失败：{last_err}\n"
            f"目标：{u}\n"
            f"{proxy_hint}\n"
            f"也可以把正文粘贴过来让我总结。"
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
