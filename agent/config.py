"""统一配置：DeepSeek API + QQ/OneBot + 运行时路径。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PKG_DIR = Path(__file__).resolve().parent
load_dotenv(_PKG_DIR / ".env", override=True)
load_dotenv(_PKG_DIR.parent / ".env", override=True)
load_dotenv(override=True)

# —— LLM ——
API_KEY = os.getenv("API_KEY")
BASE_URL = (os.getenv("BASE_URL") or "").rstrip("/")
MODEL_NAME = os.getenv("MODEL_NAME") or "deepseek-chat"
END_POINT = f"{BASE_URL}/chat/completions" if BASE_URL else ""

# —— Coding Agent 工作区（仅 agent.main CLI）——
WORKDIR = Path.cwd().resolve()
SKILLS_DIR = WORKDIR / "skills"
RUNTIME_DIR = _PKG_DIR / ".runtime"
TASKS_DIR = RUNTIME_DIR / "tasks"

# —— QQ / OneBot ——
QQ_ACCOUNT = os.getenv("QQ_ACCOUNT", "")
QQ_PASSWORD = os.getenv("QQ_PASSWORD", "")
ONEBOT_WS_URL = os.getenv("ONEBOT_WS_URL", "ws://127.0.0.1:3001")
ONEBOT_ACCESS_TOKEN = os.getenv("ONEBOT_ACCESS_TOKEN", "")
BOT_QQ = os.getenv("BOT_QQ", QQ_ACCOUNT)
# 主人 QQ：早报 / 关键词告警 / 健康告警推送目标
OWNER_QQ = os.getenv("QQ_OWNER_QQ", "") or os.getenv("OWNER_QQ", "")

# NapCat WebUI（浏览器登录后台用，不是 QQ 密码）
NAPCAT_WEBUI_HOST = os.getenv("NAPCAT_WEBUI_HOST", "127.0.0.1")
NAPCAT_WEBUI_PORT = int(os.getenv("NAPCAT_WEBUI_PORT", "6099"))
NAPCAT_WEBUI_TOKEN = os.getenv("NAPCAT_WEBUI_TOKEN", "")
NAPCAT_DIR = _PKG_DIR.parent / "napcat"
NAPCAT_WEBUI_JSON = NAPCAT_DIR / "Shell" / "config" / "webui.json"

# QQ 运行时
QQ_RUNTIME = RUNTIME_DIR / "qq"
FILES_DIR = QQ_RUNTIME / "files"  # 用户沙箱 files/{user_id}/...
# 群文件索引落盘：files/groups/{group_id}/{file_name}（对齐 /data/qqbot_files 语义）
GROUP_FILES_DIR = FILES_DIR / "groups"
MEMORY_DIR = QQ_RUNTIME / "memory"
SESSION_DIR = QQ_RUNTIME / "sessions"
SCHEDULES_DB = QQ_RUNTIME / "schedules.db"
FILES_DB = QQ_RUNTIME / "files.db"
VECTOR_DIR = QQ_RUNTIME / "vector"

# 向量后端：auto|sqlite-vec|memory（auto≈sqlite-vec，扩展缺失时 BLOB 回退）
VECTOR_BACKEND = (os.getenv("QQ_VECTOR_BACKEND") or "auto").strip().lower()
# 强制语义嵌入：1=优先 fastembed，失败时大声告警仍回退哈希（除非 QQ_FORCE_SEMANTIC=strict）
FORCE_SEMANTIC = (os.getenv("QQ_FORCE_SEMANTIC") or "1").strip().lower()

SHORT_TERM_MAX_TURNS = int(os.getenv("QQ_SHORT_TERM_MAX_TURNS", "20"))
RECALL_TOP_K = int(os.getenv("QQ_RECALL_TOP_K", "5"))
# 预召回硬截断：低于此分直接丢弃（哈希向量宜 0.28~0.4；fastembed 可调到 0.72~0.82）
RECALL_MIN_SCORE = float(os.getenv("QQ_RECALL_MIN_SCORE", "0.32") or "0.32")
SCHEDULE_HORIZON_HOURS = int(os.getenv("QQ_SCHEDULE_HORIZON_HOURS", "24"))
SCHEDULE_RELOAD_MINUTES = int(os.getenv("QQ_SCHEDULE_RELOAD_MINUTES", "60"))
GROUP_CACHE_MAXLEN = int(os.getenv("QQ_GROUP_CACHE_MAXLEN", "50"))
GROUP_CACHE_RECENT_MINUTES = int(os.getenv("QQ_GROUP_CACHE_RECENT_MINUTES", "10"))
GROUP_CACHE_SEND_LIMIT = int(os.getenv("QQ_GROUP_CACHE_SEND_LIMIT", "25"))
GROUP_CACHE_IDLE_SECONDS = int(os.getenv("QQ_GROUP_CACHE_IDLE_SECONDS", "7200"))
GROUP_AT_DEBOUNCE_SECONDS = float(os.getenv("QQ_GROUP_AT_DEBOUNCE_SECONDS", "5"))
AGENT_CONCURRENCY = int(os.getenv("QQ_AGENT_CONCURRENCY", "3"))
# 同一用户连续 @ 冷却（秒）
USER_COOLDOWN_SECONDS = float(os.getenv("QQ_USER_COOLDOWN_SECONDS", "3"))
# 回复分片间隔（会被 jitter 覆盖为随机区间）
REPLY_CHUNK_DELAY = float(os.getenv("QQ_REPLY_CHUNK_DELAY", "1.0"))
SEND_RETRY = int(os.getenv("QQ_SEND_RETRY", "3"))
SEND_RETRY_DELAY = float(os.getenv("QQ_SEND_RETRY_DELAY", "2.0"))
# 令牌桶：容量 / 每秒补充；抖动发送间隔；风控熔断
SEND_BUCKET_CAPACITY = float(os.getenv("QQ_SEND_BUCKET_CAPACITY", "5"))
SEND_BUCKET_REFILL = float(os.getenv("QQ_SEND_BUCKET_REFILL", "0.8"))
SEND_JITTER_MIN = float(os.getenv("QQ_SEND_JITTER_MIN", "1.2"))
SEND_JITTER_MAX = float(os.getenv("QQ_SEND_JITTER_MAX", "2.8"))
SEND_BREAKER_FAILS = int(os.getenv("QQ_SEND_BREAKER_FAILS", "3"))
SEND_BREAKER_COOL = float(os.getenv("QQ_SEND_BREAKER_COOL", "120"))
# 群缓存滚动摘要：满 N 条时把更早的压成摘要（烧极少 Token）
GROUP_CACHE_SUMMARY_TRIGGER = int(os.getenv("QQ_GROUP_CACHE_SUMMARY_TRIGGER", "30"))
GROUP_CACHE_SUMMARY_KEEP = int(os.getenv("QQ_GROUP_CACHE_SUMMARY_KEEP", "10"))

# 主动能力
MORNING_BRIEF_HOUR = int(os.getenv("QQ_MORNING_BRIEF_HOUR", "8"))
MORNING_BRIEF_MINUTE = int(os.getenv("QQ_MORNING_BRIEF_MINUTE", "0"))
# 逗号分隔关键词；命中群聊 → 私聊主人（0 Token）
ALERT_KEYWORDS = [
    k.strip()
    for k in (os.getenv("QQ_ALERT_KEYWORDS") or "紧急,加急").split(",")
    if k.strip()
]
KEYWORD_ALERT_COOLDOWN = float(os.getenv("QQ_KEYWORD_ALERT_COOLDOWN", "300"))

# 健康监控
HEALTH_CHECK_SECONDS = int(os.getenv("QQ_HEALTH_CHECK_SECONDS", "60"))
HEALTH_DISCONNECT_ALERT_SECONDS = int(
    os.getenv("QQ_HEALTH_DISCONNECT_ALERT_SECONDS", "300")
)
# Server 酱 SendKey；或 SMTP
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")
ALERT_SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "")
ALERT_SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "465"))
ALERT_SMTP_USER = os.getenv("ALERT_SMTP_USER", "")
ALERT_SMTP_PASS = os.getenv("ALERT_SMTP_PASS", "")
ALERT_SMTP_TO = os.getenv("ALERT_SMTP_TO", "")

# —— Obsidian Vault 双向同步（Phase 4）——
# 本地 Vault 根目录；空=关闭入库监听与写笔记
VAULT_PATH = (os.getenv("QQ_VAULT_PATH") or "").strip()
VAULT_WATCH = (os.getenv("QQ_VAULT_WATCH", "1") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
VAULT_GIT_COMMIT = (os.getenv("QQ_VAULT_GIT_COMMIT", "1") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
VAULT_GIT_PUSH = (os.getenv("QQ_VAULT_GIT_PUSH", "0") or "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
VAULT_NOTES_SUBDIR = (os.getenv("QQ_VAULT_NOTES_SUBDIR") or "QQ Agent").strip() or "QQ Agent"
VAULT_DB = QQ_RUNTIME / "vault.db"

# —— Admin Dashboard / Magic Link ——
ADMIN_PORT = int(os.getenv("QQ_ADMIN_PORT", "0") or "0")
ADMIN_SECRET = (os.getenv("QQ_ADMIN_SECRET") or "").strip()
ADMIN_MAGIC_TTL = int(os.getenv("QQ_ADMIN_MAGIC_TTL", "900") or "900")  # 秒
# 链接里的主机：auto=局域网 IP（无公网隧道时兜底）
ADMIN_PUBLIC_HOST = (os.getenv("QQ_ADMIN_PUBLIC_HOST") or "auto").strip()
# 监听地址
ADMIN_BIND = (os.getenv("QQ_ADMIN_BIND") or "0.0.0.0").strip() or "0.0.0.0"
# 公网隧道：cloudflare（默认，免账号）| off；或直接写死 QQ_ADMIN_PUBLIC_URL
ADMIN_TUNNEL = (os.getenv("QQ_ADMIN_TUNNEL") or "cloudflare").strip().lower()
ADMIN_PUBLIC_URL = (os.getenv("QQ_ADMIN_PUBLIC_URL") or "").strip().rstrip("/")
# 签发链接后在跑 Agent 的电脑上自动打开浏览器
ADMIN_AUTO_OPEN = (os.getenv("QQ_ADMIN_AUTO_OPEN", "1") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
)


def ensure_runtime_dirs() -> None:
    for path in (
        RUNTIME_DIR,
        TASKS_DIR,
        QQ_RUNTIME,
        FILES_DIR,
        GROUP_FILES_DIR,
        MEMORY_DIR,
        SESSION_DIR,
        VECTOR_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def webui_url() -> str:
    host = NAPCAT_WEBUI_HOST or "127.0.0.1"
    if host in ("::", "0.0.0.0"):
        host = "127.0.0.1"
    return f"http://{host}:{NAPCAT_WEBUI_PORT}"


def sync_napcat_webui_token() -> str:
    """把 .env 里的 NAPCAT_WEBUI_TOKEN 同步进 napcat webui.json（若存在）。

    返回当前生效的 token（优先 env；否则读配置文件）。
    """
    import json

    token = (NAPCAT_WEBUI_TOKEN or "").strip()
    path = NAPCAT_WEBUI_JSON
    if not path.is_file():
        return token

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[config] 读取 webui.json 失败: {e}")
        return token

    file_token = str(data.get("token") or "").strip()
    if token:
        changed = False
        if data.get("token") != token:
            data["token"] = token
            changed = True
        if int(data.get("port") or 0) != NAPCAT_WEBUI_PORT:
            data["port"] = NAPCAT_WEBUI_PORT
            changed = True
        if changed:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
            print(f"[config] 已同步 NAPCAT_WEBUI_TOKEN → {path}")
        return token
    return file_token
