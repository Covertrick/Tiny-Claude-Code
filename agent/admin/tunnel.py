"""公网隧道：Cloudflare Quick Tunnel（无需账号），手机不在同一 WiFi 也能打开控制台。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from agent.config import RUNTIME_DIR

_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")
_state: dict = {
    "url": "",
    "proc": None,
    "kind": "",
}
_lock = threading.Lock()

_CF_NAME = "cloudflared-windows-amd64.exe"
_CF_VER = "2024.10.0"
# 多镜像：国内 GitHub 常超时
_CF_URLS = [
    f"https://ghfast.top/https://github.com/cloudflare/cloudflared/releases/download/{_CF_VER}/{_CF_NAME}",
    f"https://mirror.ghproxy.com/https://github.com/cloudflare/cloudflared/releases/download/{_CF_VER}/{_CF_NAME}",
    f"https://github.com/cloudflare/cloudflared/releases/download/{_CF_VER}/{_CF_NAME}",
]


def get_public_base_url() -> str:
    """运行时公网基址（无尾斜杠），无则空串。"""
    env = (os.getenv("QQ_ADMIN_PUBLIC_URL") or "").strip().rstrip("/")
    if env:
        return env
    with _lock:
        return str(_state.get("url") or "")


def set_public_base_url(url: str) -> None:
    with _lock:
        _state["url"] = (url or "").strip().rstrip("/")


def _bin_dir() -> Path:
    d = RUNTIME_DIR / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "TinyQQAgent/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def _ensure_cloudflared() -> Path | None:
    which = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if which:
        return Path(which)
    local = _bin_dir() / "cloudflared.exe"
    if local.is_file() and local.stat().st_size > 1_000_000:
        return local
    if local.is_file():
        try:
            local.unlink()
        except Exception:
            pass
    print("[tunnel] 下载 cloudflared（一次性，可能需 1～2 分钟）…")
    last_err: Exception | None = None
    tmp = local.with_suffix(".download")
    for url in _CF_URLS:
        try:
            print(f"[tunnel] 尝试 {url[:64]}…")
            if tmp.is_file():
                tmp.unlink()
            _download(url, tmp)
            if tmp.stat().st_size < 1_000_000:
                raise RuntimeError(f"文件过小: {tmp.stat().st_size}")
            tmp.replace(local)
            print(f"[tunnel] 已保存 {local} ({local.stat().st_size} bytes)")
            return local
        except Exception as e:
            last_err = e
            print(f"[tunnel] 失败: {e}")
    print(f"[tunnel] 全部镜像失败: {last_err}")
    return None


def _start_cloudflared(local_port: int) -> str:
    exe = _ensure_cloudflared()
    if exe is None:
        raise RuntimeError(
            "未找到 cloudflared。可手动安装后设 QQ_ADMIN_TUNNEL=cloudflare，"
            "或直接设 QQ_ADMIN_PUBLIC_URL=你的公网HTTPS地址"
        )
    target = f"http://127.0.0.1:{local_port}"
    proc = subprocess.Popen(
        [str(exe), "tunnel", "--url", target, "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    url = ""
    deadline = time.time() + 45
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            print(f"[tunnel] {line.rstrip()}")
            m = _URL_RE.search(line)
            if m:
                url = m.group(0)
                break
    if not url:
        try:
            proc.terminate()
        except Exception:
            pass
        raise RuntimeError("cloudflared 未在时限内给出公网 URL（网络可能被拦）")
    with _lock:
        _state["proc"] = proc
        _state["url"] = url
        _state["kind"] = "cloudflare"
    # 继续吞日志，避免管道堵死
    def _drain() -> None:
        try:
            while proc.poll() is None:
                proc.stdout.readline()
        except Exception:
            pass

    threading.Thread(target=_drain, daemon=True).start()
    return url


def start_admin_tunnel(local_port: int) -> str:
    """同步启动；成功返回 https 基址。"""
    kind = (os.getenv("QQ_ADMIN_TUNNEL") or "cloudflare").strip().lower()
    preset = (os.getenv("QQ_ADMIN_PUBLIC_URL") or "").strip().rstrip("/")
    if preset:
        set_public_base_url(preset)
        print(f"[tunnel] 使用预设公网地址 {preset}")
        return preset
    if kind in ("0", "off", "false", "no", "none", ""):
        print("[tunnel] 已关闭（QQ_ADMIN_TUNNEL=off）")
        return ""
    if kind in ("cloudflare", "cf", "trycloudflare", "1", "true", "yes", "auto"):
        url = _start_cloudflared(local_port)
        print(f"[tunnel] 公网控制台 {url}/dash")
        return url
    if kind == "ngrok":
        raise RuntimeError("ngrok 请自行启动并设 QQ_ADMIN_PUBLIC_URL=https://xxx.ngrok-free.app")
    raise RuntimeError(f"未知 QQ_ADMIN_TUNNEL={kind}")


def start_admin_tunnel_async(local_port: int) -> None:
    """后台拉隧道，不堵住 Agent 启动。"""

    def _job() -> None:
        try:
            start_admin_tunnel(local_port)
        except Exception as e:
            print(f"[tunnel] 公网隧道未启动: {e}")

    threading.Thread(target=_job, name="admin-tunnel", daemon=True).start()


def wait_public_base_url(*, timeout: float = 20.0) -> str:
    """等待隧道 URL（签发 Magic Link 前可短等）。"""
    preset = (os.getenv("QQ_ADMIN_PUBLIC_URL") or "").strip().rstrip("/")
    if preset:
        return preset
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = get_public_base_url()
        if url.startswith("https://"):
            return url
        time.sleep(0.4)
    return get_public_base_url()


def stop_admin_tunnel() -> None:
    with _lock:
        proc = _state.get("proc")
        _state["proc"] = None
        _state["url"] = ""
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
