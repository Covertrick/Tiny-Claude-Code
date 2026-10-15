"""主动资讯订阅：RSS / GitHub Release + 可选定时推送。"""

from __future__ import annotations

import json
import os
import urllib.request
import xml.etree.ElementTree as ET

from apscheduler.triggers.cron import CronTrigger


def _rss_urls() -> list[str]:
    raw = os.getenv("QQ_RSS_URLS", "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return ["https://www.solidot.org/index.rss"]


def _github_repos() -> list[str]:
    raw = os.getenv("QQ_GITHUB_REPOS", "").strip()
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def _fetch_rss(url: str, *, limit: int = 5) -> list[dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "TinyQQAgent/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        items.append({"title": title, "link": link, "source": "rss"})
    # Atom
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns)[:limit]:
            title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
            link_el = entry.find("a:link", ns)
            href = link_el.get("href") if link_el is not None else ""
            items.append({"title": title, "link": href, "source": "atom"})
    return items


def _fetch_github_releases(repo: str, *, limit: int = 2) -> list[dict[str, str]]:
    # repo: owner/name
    url = f"https://api.github.com/repos/{repo}/releases?per_page={limit}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TinyQQAgent/1.0",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for rel in data[:limit]:
        out.append(
            {
                "title": f"{repo} {rel.get('tag_name') or ''}: {rel.get('name') or ''}",
                "link": rel.get("html_url") or "",
                "source": "github",
            }
        )
    return out


def fetch_digest(urls: list[str] | None = None, *, use_llm: bool = False) -> str:
    urls = urls or _rss_urls()
    lines: list[str] = []
    for url in urls[:4]:
        try:
            for it in _fetch_rss(url, limit=3):
                if it["title"]:
                    lines.append(f"· {it['title']}")
        except Exception as e:
            lines.append(f"· （RSS 失败 {url[:48]}…）")
    for repo in _github_repos()[:3]:
        try:
            for it in _fetch_github_releases(repo):
                if it["title"].strip():
                    lines.append(f"· {it['title'].strip()}")
        except Exception:
            lines.append(f"· （GitHub 失败 {repo}）")
    if not lines:
        return "今天没有拉到资讯。可在 .env 配 QQ_RSS_URLS / QQ_GITHUB_REPOS。"
    text = "今日速递：\n" + "\n".join(lines[:10])
    if not use_llm:
        return text
    try:
        from agent.channel.trust import wrap_untrusted
        from agent.core.llm import chat

        msg = chat(
            [
                {
                    "role": "system",
                    "content": "把资讯压成最多3条中文短讯，口语，无 Markdown。",
                },
                {"role": "user", "content": wrap_untrusted("rss", text)},
            ],
            tools=None,
            max_tokens=180,
            timeout=45,
        )
        return (msg.get("content") or text).strip()
    except Exception:
        return text


def register_digest_job(scheduler) -> None:
    """定时私聊主人推送速递（0 Token，除非 QQ_DIGEST_USE_LLM=1）。"""
    from agent.config import OWNER_QQ

    if not OWNER_QQ:
        print("[digest] 未配置 QQ_OWNER_QQ，跳过定时速递")
        return
    aps = getattr(scheduler, "_aps", None)
    if aps is None:
        return
    hour = int(os.getenv("QQ_DIGEST_HOUR", "8"))
    minute = int(os.getenv("QQ_DIGEST_MINUTE", "30"))
    use_llm = os.getenv("QQ_DIGEST_USE_LLM", "").strip() in ("1", "true", "yes")

    def _job() -> None:
        try:
            text = fetch_digest(use_llm=use_llm)
            from agent.channel.send import safe_send_msg

            safe_send_msg(
                scheduler.client, user_id=OWNER_QQ, message=text, chunk=False
            )
            print(f"[digest] 已推送速递 → {OWNER_QQ}")
        except Exception as e:
            print(f"[digest] 推送失败: {e}")

    aps.add_job(
        _job,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai"),
        id="rss_digest",
        replace_existing=True,
        max_instances=1,
    )
    print(f"[digest] 定时速递 {hour:02d}:{minute:02d} → {OWNER_QQ}")
