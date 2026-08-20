"""环境与路径配置：从 agent/.env 读取 API，并定义 WORKDIR / 运行时目录。"""

import os
from pathlib import Path

from dotenv import load_dotenv

_PKG_DIR = Path(__file__).resolve().parent
load_dotenv(_PKG_DIR / ".env", override=True)
load_dotenv(override=True)

API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL") or ""
MODEL_NAME = os.getenv("MODEL_NAME")
END_POINT = f"{BASE_URL.rstrip('/')}/chat/completions"
WORKDIR = Path.cwd().resolve()
SKILLS_DIR = WORKDIR / "skills"
# 运行时落盘（压缩归档、工具大输出、记忆），跟源码包放一起
RUNTIME_DIR = _PKG_DIR / ".runtime"
TASKS_DIR = RUNTIME_DIR / "tasks"
