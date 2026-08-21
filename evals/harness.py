"""评测工作区隔离、usage 统计、单题跑 agent。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class UsageTracker:
    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.calls = 0

    def on_usage(self, usage: dict) -> None:
        self.calls += 1
        pt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        ct = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        tt = int(usage.get("total_tokens") or (pt + ct))
        self.prompt_tokens += pt
        self.completion_tokens += ct
        self.total_tokens += tt

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_calls": self.calls,
        }


@contextmanager
def temporary_workspace(prefix: str = "tcc-eval-"):
    """独立临时目录作为 WORKDIR，并补丁相关模块。"""
    workspace = Path(tempfile.mkdtemp(prefix=prefix))
    (workspace / "skills").mkdir(exist_ok=True)
    # 拷一份最小 skills 目录可选：不拷也能跑
    old_cwd = Path.cwd()
    try:
        os.chdir(workspace)
        import agent.config as cfg
        import agent.hooks.permission as perm
        import agent.skill_load.loader as loader
        import agent.tools.base as base

        patches = {
            "cfg": cfg.WORKDIR,
            "base": base.WORKDIR,
            "perm": perm.WORKDIR,
            "loader": loader.WORKDIR,
        }
        cfg.WORKDIR = workspace
        base.WORKDIR = workspace
        perm.WORKDIR = workspace
        loader.WORKDIR = workspace
        # skills 目录指向空目录即可
        loader.SKILLS_DIR = workspace / "skills"
        if hasattr(loader, "SKILL_LOADER"):
            loader.SKILL_LOADER.skills_dir = workspace / "skills"
            loader.SKILL_LOADER.scan()
        yield workspace
    finally:
        os.chdir(old_cwd)
        try:
            cfg.WORKDIR = patches["cfg"]
            base.WORKDIR = patches["base"]
            perm.WORKDIR = patches["perm"]
            loader.WORKDIR = patches["loader"]
        except Exception:
            pass
        shutil.rmtree(workspace, ignore_errors=True)


def tool_names_from_history(messages: list) -> list[str]:
    names = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = (tc.get("function") or {}).get("name")
            if fn:
                names.append(fn)
    return names


def tool_outputs_from_history(messages: list) -> list[str]:
    return [
        str(m.get("content", ""))
        for m in messages
        if m.get("role") == "tool"
    ]


def run_agent_once(prompt: str, auto_approve: bool = True) -> dict[str, Any]:
    """在当前 WORKDIR 跑一轮 agent_loop；返回轨迹与 usage。"""
    from agent.core.llm import set_usage_hook
    from agent.core.loop import agent_loop
    from agent.hooks import trigger_hook
    from agent.memory import build_system

    tracker = UsageTracker()
    set_usage_hook(tracker.on_usage)
    history = [{"role": "system", "content": build_system()}]
    started = time.time()
    try:
        trigger_hook("UserPromptSubmit", prompt)
        history.append({"role": "user", "content": prompt})
        input_side = "y" if auto_approve else "n"
        with patch("builtins.input", return_value=input_side):
            agent_loop(history, active_request=prompt)
        error = None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        set_usage_hook(None)
    elapsed = time.time() - started
    return {
        "messages": history,
        "tool_names": tool_names_from_history(history),
        "tool_outputs": tool_outputs_from_history(history),
        "usage": tracker.as_dict(),
        "elapsed_sec": round(elapsed, 2),
        "error": error,
        "final_text": _final_assistant_text(history),
    }


def _final_assistant_text(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and not msg.get("tool_calls"):
            content = msg.get("content")
            return content if isinstance(content, str) else str(content or "")
    return ""


def load_json_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("cases", [])
