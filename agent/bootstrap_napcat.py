"""启动前引导：补全 .env、拉起 NapCat、等待 OneBot WS。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv

_PKG = Path(__file__).resolve().parent
_ROOT = _PKG.parent
_ENV = _PKG / ".env"
_ENV_EXAMPLE = _PKG / ".env.example"
_NAPCAT_SHELL = _ROOT / "napcat" / "Shell"
_WEBUI_JSON = _NAPCAT_SHELL / "config" / "webui.json"


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _read_env_map(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def _upsert_env(path: Path, updates: dict[str, str]) -> list[str]:
    """写入/更新 .env 键；返回实际改动的 key 列表。"""
    if not path.is_file():
        path.write_text("", encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    changed: list[str] = []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        raw = line
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, old = s.partition("=")
            key = k.strip()
            if key in updates:
                seen.add(key)
                val = updates[key]
                if old.strip() != val:
                    new_lines.append(f"{key}={val}")
                    changed.append(key)
                else:
                    new_lines.append(raw)
                continue
        new_lines.append(raw)
    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")
            changed.append(key)
    if changed:
        text = "\n".join(new_lines).rstrip() + "\n"
        path.write_text(text, encoding="utf-8")
    return changed


def ensure_env_file() -> None:
    """没有 .env 则从 .env.example 复制。"""
    if _ENV.is_file():
        return
    if _ENV_EXAMPLE.is_file():
        _ENV.write_text(_ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[bootstrap] 已从 .env.example 创建 {_ENV}")
    else:
        _ENV.write_text(
            "API_KEY=\nBASE_URL=https://api.deepseek.com\nMODEL_NAME=deepseek-chat\n"
            "ONEBOT_WS_URL=ws://127.0.0.1:3001\n"
            "NAPCAT_WEBUI_HOST=127.0.0.1\nNAPCAT_WEBUI_PORT=6099\nNAPCAT_WEBUI_TOKEN=\n",
            encoding="utf-8",
        )
        print(f"[bootstrap] 已创建空 {_ENV}")


def fill_env_from_napcat() -> dict[str, str]:
    """从 NapCat webui.json / 账号配置自动填 .env。"""
    ensure_env_file()
    updates: dict[str, str] = {}
    cur = _read_env_map(_ENV)

    # 默认连接
    if not cur.get("ONEBOT_WS_URL"):
        updates["ONEBOT_WS_URL"] = "ws://127.0.0.1:3001"
    if not cur.get("NAPCAT_WEBUI_HOST"):
        updates["NAPCAT_WEBUI_HOST"] = "127.0.0.1"
    if not cur.get("NAPCAT_WEBUI_PORT"):
        updates["NAPCAT_WEBUI_PORT"] = "6099"

    # WebUI token / port 从配置文件回填
    if _WEBUI_JSON.is_file():
        try:
            data = json.loads(_WEBUI_JSON.read_text(encoding="utf-8"))
            token = str(data.get("token") or "").strip()
            port = str(data.get("port") or "").strip()
            if token and cur.get("NAPCAT_WEBUI_TOKEN") != token:
                updates["NAPCAT_WEBUI_TOKEN"] = token
            if port and not cur.get("NAPCAT_WEBUI_PORT"):
                updates["NAPCAT_WEBUI_PORT"] = port
        except Exception as e:
            print(f"[bootstrap] 读 webui.json 失败: {e}")

    # BOT_QQ / QQ_ACCOUNT：扫 onebot 配置文件名 onebot11_{qq}.json
    cfg_dir = _NAPCAT_SHELL / "config"
    if cfg_dir.is_dir():
        qq_from_cfg = ""
        for p in cfg_dir.glob("onebot11_*.json"):
            stem = p.stem  # onebot11_1963535087
            parts = stem.split("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                qq_from_cfg = parts[1]
                break
        if qq_from_cfg:
            if not cur.get("QQ_ACCOUNT"):
                updates["QQ_ACCOUNT"] = qq_from_cfg
            if not cur.get("BOT_QQ"):
                updates["BOT_QQ"] = qq_from_cfg

    changed = _upsert_env(_ENV, updates)
    if changed:
        print(f"[bootstrap] 已自动写入 .env: {', '.join(changed)}")
    else:
        print("[bootstrap] .env 已就绪（无需改写）")
    load_dotenv(_ENV, override=True)
    return _read_env_map(_ENV)


def _pick_launcher() -> Path | None:
    for name in (
        "launcher-user.bat",
        "launcher-win10-user.bat",
        "launcher.bat",
        "launcher-win10.bat",
    ):
        p = _NAPCAT_SHELL / name
        if p.is_file():
            return p
    return None


def start_napcat_if_needed(*, ws_port: int = 3001, webui_port: int = 6099) -> bool:
    """若 OneBot / WebUI 端口未开，则启动 NapCat launcher。"""
    if _port_open("127.0.0.1", ws_port):
        print(f"[bootstrap] NapCat OneBot 已在监听 :{ws_port}")
        return True

    if not _NAPCAT_SHELL.is_dir():
        print(f"[bootstrap] 未找到 NapCat 目录: {_NAPCAT_SHELL}")
        return False

    launcher = _pick_launcher()
    if launcher is None:
        print("[bootstrap] 未找到 launcher*.bat")
        return False

    env_map = _read_env_map(_ENV)
    qq = env_map.get("QQ_ACCOUNT") or env_map.get("BOT_QQ") or ""
    # launcher*.bat 把 %* 传给 NapCatWinBootMain；-q <QQ> 为快捷登录
    args = ["cmd.exe", "/c", launcher.name]
    if qq.isdigit():
        args.extend(["-q", qq])

    print(f"[bootstrap] 正在启动 NapCat: {launcher.name} …")
    try:
        # 独立控制台，不阻塞 Agent
        flags = 0
        if hasattr(subprocess, "CREATE_NEW_CONSOLE"):
            flags |= subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
        subprocess.Popen(
            args,
            cwd=str(_NAPCAT_SHELL),
            creationflags=flags,
        )
    except Exception as e:
        print(f"[bootstrap] 启动 NapCat 失败: {e}")
        return False

    # 等待端口
    deadline = time.time() + 90
    while time.time() < deadline:
        ws_ok = _port_open("127.0.0.1", ws_port)
        ui_ok = _port_open("127.0.0.1", webui_port)
        if ws_ok:
            print(f"[bootstrap] OneBot WS 已就绪 :{ws_port}")
            if ui_ok:
                print(f"[bootstrap] WebUI 已就绪 :{webui_port}")
            # 启动后 webui.json 可能刚生成/刷新，再填一次 .env
            fill_env_from_napcat()
            return True
        time.sleep(2)
        print("[bootstrap] 等待 NapCat 就绪（可能需要扫码登录）…")

    print(
        f"[bootstrap] 等待超时：请确认 NapCat 窗口已登录 QQ，"
        f"且正向 WS 端口为 {ws_port}"
    )
    # 再试填一次 token
    fill_env_from_napcat()
    return _port_open("127.0.0.1", ws_port)


def reload_agent_config() -> None:
    """把最新 .env 刷进 agent.config 模块级变量。"""
    import agent.config as cfg

    load_dotenv(_ENV, override=True)
    cfg.API_KEY = os.getenv("API_KEY")
    cfg.BASE_URL = (os.getenv("BASE_URL") or "").rstrip("/")
    cfg.MODEL_NAME = os.getenv("MODEL_NAME") or "deepseek-chat"
    cfg.END_POINT = (
        f"{cfg.BASE_URL}/chat/completions" if cfg.BASE_URL else ""
    )
    cfg.QQ_ACCOUNT = os.getenv("QQ_ACCOUNT", "")
    cfg.QQ_PASSWORD = os.getenv("QQ_PASSWORD", "")
    cfg.ONEBOT_WS_URL = os.getenv("ONEBOT_WS_URL", "ws://127.0.0.1:3001")
    cfg.ONEBOT_ACCESS_TOKEN = os.getenv("ONEBOT_ACCESS_TOKEN", "")
    cfg.BOT_QQ = os.getenv("BOT_QQ", cfg.QQ_ACCOUNT)
    cfg.OWNER_QQ = os.getenv("QQ_OWNER_QQ", "") or os.getenv("OWNER_QQ", "")
    cfg.NAPCAT_WEBUI_HOST = os.getenv("NAPCAT_WEBUI_HOST", "127.0.0.1")
    cfg.NAPCAT_WEBUI_PORT = int(os.getenv("NAPCAT_WEBUI_PORT", "6099"))
    cfg.NAPCAT_WEBUI_TOKEN = os.getenv("NAPCAT_WEBUI_TOKEN", "")


def _ensure_localhost_no_proxy() -> None:
    """本机 OneBot/WebUI 不要走系统代理，否则 WS 握手会立刻断。"""
    extra = "127.0.0.1,localhost"
    for key in ("NO_PROXY", "no_proxy"):
        cur = os.environ.get(key, "")
        parts = [p.strip() for p in cur.split(",") if p.strip()]
        for host in extra.split(","):
            if host not in parts:
                parts.append(host)
        os.environ[key] = ",".join(parts)


def bootstrap(*, auto_start_napcat: bool = True) -> dict[str, str]:
    """一键：补 .env → 启 NapCat → 再刷配置。"""
    print("[bootstrap] 开始引导…")
    _ensure_localhost_no_proxy()
    env_map = fill_env_from_napcat()
    ws_port = 3001
    try:
        url = env_map.get("ONEBOT_WS_URL") or "ws://127.0.0.1:3001"
        # ws://127.0.0.1:3001
        host_port = url.split("//", 1)[-1]
        if ":" in host_port:
            ws_port = int(host_port.rsplit(":", 1)[-1].split("/")[0])
    except Exception:
        ws_port = 3001
    webui_port = int(env_map.get("NAPCAT_WEBUI_PORT") or "6099")

    if auto_start_napcat:
        start_napcat_if_needed(ws_port=ws_port, webui_port=webui_port)
        env_map = fill_env_from_napcat()

    reload_agent_config()
    return env_map
