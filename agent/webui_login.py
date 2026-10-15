"""NapCat WebUI 自动登录：读 Token → 换 Credential → 浏览器写入 localStorage。

算法与官方一致：POST /api/auth/login  body={"hash": sha256(token + ".napcat")}
成功后把 Credential 写入同源 localStorage.token，并打开控制台。

用法：
  python -m agent.webui_login
  python -m agent.webui_login --no-open   # 只换票，不打开浏览器
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

_PKG = Path(__file__).resolve().parent


def _load_token() -> tuple[str, str, int]:
    """返回 (token, host, port)。优先 .env，其次 webui.json。"""
    from dotenv import load_dotenv

    load_dotenv(_PKG / ".env", override=True)
    host = os.getenv("NAPCAT_WEBUI_HOST", "127.0.0.1") or "127.0.0.1"
    port = int(os.getenv("NAPCAT_WEBUI_PORT", "6099") or "6099")
    token = (os.getenv("NAPCAT_WEBUI_TOKEN") or "").strip()

    if not token:
        # 引导从 webui.json 同步
        try:
            from agent.bootstrap_napcat import fill_env_from_napcat

            fill_env_from_napcat()
            load_dotenv(_PKG / ".env", override=True)
            token = (os.getenv("NAPCAT_WEBUI_TOKEN") or "").strip()
            host = os.getenv("NAPCAT_WEBUI_HOST", host) or host
            port = int(os.getenv("NAPCAT_WEBUI_PORT", str(port)) or port)
        except Exception:
            pass

    if not token:
        webui_json = _PKG.parent / "napcat" / "Shell" / "config" / "webui.json"
        if webui_json.is_file():
            data = json.loads(webui_json.read_text(encoding="utf-8"))
            token = str(data.get("token") or "").strip()
            if data.get("port"):
                port = int(data["port"])

    return token, host, port


def password_hash(token: str) -> str:
    return hashlib.sha256((token + ".napcat").encode("utf-8")).hexdigest()


def fetch_credential(token: str, *, host: str = "127.0.0.1", port: int = 6099) -> str:
    """用 WebUI Token 换取 Credential（base64）。"""
    url = f"http://{host}:{port}/api/auth/login"
    body = json.dumps({"hash": password_hash(token)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"连不上 WebUI {url}：{e}") from e

    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or "登录失败")
    data = payload.get("data") or {}
    cred = data.get("Credential") or data.get("credential")
    if not cred:
        raise RuntimeError("响应里没有 Credential")
    return str(cred)


def _browser_candidates() -> list[str]:
    names = []
    for key in (
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
    ):
        root = os.environ.get(key) or ""
        if not root:
            continue
        names.extend(
            [
                str(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            ]
        )
    # PATH
    for exe in ("msedge", "chrome", "msedge.exe", "chrome.exe"):
        p = shutil.which(exe)
        if p:
            names.append(p)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen and Path(n).is_file():
            seen.add(n)
            out.append(n)
    return out


def _cdp_json(port: int, path: str = "/json/list") -> list | dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def _pick_debug_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def inject_credential_via_cdp(
    credential: str,
    *,
    host: str,
    port: int,
    debug_port: int | None = None,
) -> bool:
    """拉起 Edge/Chrome（独立 user-data），用 CDP 写入 localStorage 并进控制台。"""
    import websocket

    browsers = _browser_candidates()
    if not browsers:
        return False

    debug_port = debug_port or _pick_debug_port()
    profile = Path(tempfile.mkdtemp(prefix="napcat_webui_"))
    target = f"http://{host}:{port}/webui/"
    login_url = f"http://{host}:{port}/webui/web_login"
    browser = browsers[0]
    args = [
        browser,
        f"--remote-debugging-port={debug_port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        login_url,
    ]
    print(f"[webui] 启动浏览器自动填 Token（debug={debug_port}）…")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 等 CDP（必须带 allow-origins，故只连我们刚拉起的端口）
    page = None
    for _ in range(60):
        time.sleep(0.3)
        try:
            tabs = _cdp_json(debug_port)
            if isinstance(tabs, list):
                for t in tabs:
                    if t.get("type") == "page" and "webui" in (t.get("url") or ""):
                        page = t
                        break
                if page is None and tabs:
                    page = next((t for t in tabs if t.get("type") == "page"), tabs[0])
            if page and page.get("webSocketDebuggerUrl"):
                break
        except Exception:
            if proc.poll() is not None:
                return False
            continue
    if not page or not page.get("webSocketDebuggerUrl"):
        try:
            proc.terminate()
        except Exception:
            pass
        return False

    ws_url = page["webSocketDebuggerUrl"]
    ws = websocket.create_connection(
        ws_url,
        timeout=10,
        http_proxy_host=None,
        suppress_origin=True,
    )

    def call(method: str, params: dict | None = None, oid: int = 1) -> dict:
        payload = {"id": oid, "method": method, "params": params or {}}
        ws.send(json.dumps(payload))
        deadline = time.time() + 10
        while time.time() < deadline:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == oid:
                return msg
        raise TimeoutError(method)

    call("Page.enable", {}, 1)
    call("Page.navigate", {"url": login_url}, 2)
    time.sleep(1.2)

    # localStorage 存的是 JSON 字符串（前端 JSON.stringify(Credential)）
    js = (
        "(() => {"
        f"const c = {json.dumps(credential)};"
        "localStorage.setItem('token', JSON.stringify(c));"
        f"location.replace({json.dumps(target)});"
        "return 'ok';"
        "})()"
    )
    result = call("Runtime.evaluate", {"expression": js, "awaitPromise": False}, 3)
    ws.close()
    if result.get("error"):
        print(f"[webui] CDP 执行失败: {result['error']}")
        return False
    print(f"[webui] 已自动登录并打开：{target}")
    return True


def open_webui_manual(host: str, port: int, token: str) -> None:
    url = f"http://{host}:{port}/webui/web_login"
    print(f"[webui] 请手动打开并粘贴 Token：{token}")
    print(f"[webui] {url}")
    webbrowser.open(url)


def auto_login_and_open(*, open_browser: bool = True) -> str:
    """同步 .env Token → 换票 →（可选）自动填入浏览器。返回 Credential。"""
    # 先尽量把 webui.json 同步进 .env
    try:
        from agent.bootstrap_napcat import fill_env_from_napcat

        fill_env_from_napcat()
    except Exception:
        pass

    token, host, port = _load_token()
    if not token:
        raise RuntimeError("未找到 NAPCAT_WEBUI_TOKEN（检查 agent/.env 或 webui.json）")

    print(f"[webui] Token={token}  → http://{host}:{port}")
    cred = fetch_credential(token, host=host, port=port)
    print("[webui] Credential 已签发")

    if open_browser:
        ok = False
        try:
            ok = inject_credential_via_cdp(cred, host=host, port=port)
        except Exception as e:
            print(f"[webui] 自动填入失败：{e}")
        if not ok:
            open_webui_manual(host, port, token)
            print("[webui] 已打开登录页；Token 见上方，粘贴即可（或装 Edge/Chrome 以便下次全自动）")
    return cred


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NapCat WebUI 自动登录")
    parser.add_argument(
        "--no-open", action="store_true", help="只换票，不打开浏览器"
    )
    args = parser.parse_args(argv)
    try:
        auto_login_and_open(open_browser=not args.no_open)
        return 0
    except Exception as e:
        print(f"[webui] 失败：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
