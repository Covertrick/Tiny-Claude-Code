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

SHORT_TERM_MAX_TURNS = int(os.getenv("QQ_SHORT_TERM_MAX_TURNS", "20"))
RECALL_TOP_K = int(os.getenv("QQ_RECALL_TOP_K", "5"))
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
# 回复分片间隔
REPLY_CHUNK_DELAY = float(os.getenv("QQ_REPLY_CHUNK_DELAY", "1.0"))
SEND_RETRY = int(os.getenv("QQ_SEND_RETRY", "3"))
SEND_RETRY_DELAY = float(os.getenv("QQ_SEND_RETRY_DELAY", "2.0"))

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


def ensure_runtime_dirs() -> None:
    for path in (
        RUNTIME_DIR,
        TASKS_DIR,
        QQ_RUNTIME,
        FILES_DIR,
        GROUP_FILES_DIR,
        MEMORY_DIR,
        SESSION_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
