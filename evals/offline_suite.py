"""离线评测：不调 LLM，验证权限 / 任务图 / 后台 / MCP 池。"""

from __future__ import annotations

import time
from typing import Callable
from unittest.mock import patch

from agent.background import BACKGROUND, inject_background_results
from agent.config import RUNTIME_DIR
from agent.core.execute import execute_tool
from agent.hooks.permission import permission_hook
from agent.mcp import assemble_tool_pool, connect_mcp
from agent.mcp.connect import mcp_clients
from agent.tasks import store as store_mod
from agent.tasks.store import TaskStore
from agent.tools import TASK_TOOLS, TOOL_HANDLERS
from agent.tools.base import BASE_HANDLERS


def _case(cid: str, category: str, name: str, fn: Callable[[], None]) -> dict:
    try:
        fn()
        return {
            "id": cid,
            "category": category,
            "name": name,
            "mode": "offline",
            "passed": True,
            "detail": "ok",
            "usage": {"total_tokens": 0},
        }
    except Exception as exc:
        return {
            "id": cid,
            "category": category,
            "name": name,
            "mode": "offline",
            "passed": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "usage": {"total_tokens": 0},
        }


def _clear_store(store: TaskStore) -> None:
    root = store._root(create=True)
    for path in root.glob("task_*.json"):
        path.unlink()


def run_offline() -> list[dict]:
    results = []

    # ---- B permission ----
    def b_deny_rm():
        out = permission_hook("bash", {"command": "rm -rf /"})
        assert out and "拒绝" in out

    results.append(_case("B01", "B", "deny rm -rf /", b_deny_rm))

    def b_deny_sudo():
        out = permission_hook("bash", {"command": "sudo reboot"})
        assert out and "拒绝" in out

    results.append(_case("B02", "B", "deny sudo", b_deny_sudo))

    def b_path_reject():
        with patch("builtins.input", return_value="n"):
            out = permission_hook("read", {"path": "../outside.txt"})
        assert out and "拒绝" in out

    results.append(_case("B03", "B", "path escape reject on n", b_path_reject))

    def b_path_allow():
        with patch("builtins.input", return_value="y"):
            out = permission_hook("read", {"path": "../outside.txt"})
        assert out is None

    results.append(_case("B04", "B", "path escape allow on y", b_path_allow))

    def b_mcp_confirm_reject():
        mcp_clients.clear()
        connect_mcp("deploy")
        assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)
        with patch("builtins.input", return_value="n"):
            out = permission_hook("mcp__deploy__trigger", {"service": "api"})
        assert out and "拒绝" in out

    results.append(_case("B05", "B", "mcp trigger confirm reject", b_mcp_confirm_reject))

    def b_mcp_allow_no_prompt():
        mcp_clients.clear()
        connect_mcp("docs")
        assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)
        out = permission_hook("mcp__docs__search", {"query": "x"})
        assert out is None

    results.append(_case("B06", "B", "mcp search allow silent", b_mcp_allow_no_prompt))

    def b_safe_bash_ok():
        out = permission_hook("bash", {"command": "echo hello"})
        assert out is None

    results.append(_case("B07", "B", "safe bash passes", b_safe_bash_ok))

    # ---- C task graph（隔离 TaskStore）----
    store = TaskStore(RUNTIME_DIR / "evals_offline_tasks")
    old_tasks = store_mod.TASKS
    store_mod.TASKS = store

    def c_flow():
        _clear_store(store)
        t1 = store_mod.create_task("设计")
        t2 = store_mod.create_task("实现")
        store_mod.update_task(t2.id, [t1.id])
        assert not store_mod.can_start(t2.id)
        msg = store_mod.claim_task(t1.id, owner="agent")
        assert "已认领" in msg
        assert store.load(t1.id).status == "in_progress"
        store_mod.complete_task(t1.id, owner="agent")
        assert store.load(t1.id).status == "completed"
        assert store_mod.can_start(t2.id)
        store_mod.claim_task(t2.id, owner="agent")
        store_mod.complete_task(t2.id, owner="agent")
        assert store.load(t2.id).status == "completed"

    results.append(_case("C01", "C", "dependency claim order", c_flow))

    def c_block_early_claim():
        _clear_store(store)
        t1 = store_mod.create_task("x")
        t2 = store_mod.create_task("y")
        store_mod.update_task(t2.id, [t1.id])
        msg = store_mod.claim_task(t2.id, owner="agent")
        assert "阻塞" in msg
        assert store.load(t2.id).status == "pending"

    results.append(_case("C02", "C", "cannot claim blocked", c_block_early_claim))

    def c_cycle_reject():
        _clear_store(store)
        t1 = store_mod.create_task("p")
        t2 = store_mod.create_task("q")
        store_mod.update_task(t2.id, [t1.id])
        try:
            store_mod.update_task(t1.id, [t2.id])
            raise AssertionError("cycle should raise")
        except ValueError:
            pass

    results.append(_case("C03", "C", "reject dependency cycle", c_cycle_reject))

    def c_self_dep():
        _clear_store(store)
        t1 = store_mod.create_task("solo")
        try:
            store_mod.update_task(t1.id, [t1.id])
            raise AssertionError("self dep should raise")
        except ValueError:
            pass

    results.append(_case("C04", "C", "reject self dependency", c_self_dep))

    store_mod.TASKS = old_tasks

    # ---- D background ----
    def d_bg_placeholder_and_notify():
        BACKGROUND.tasks.clear()
        BACKGROUND.results.clear()
        BACKGROUND._ready.clear()
        BACKGROUND._counter = 0
        started = time.time()
        with patch("builtins.input", return_value="y"):
            out = execute_tool(
                "bash",
                {"command": "ping -n 2 127.0.0.1", "run_in_background": True},
                BASE_HANDLERS,
                tool_call_id="eval-tc",
            )
        elapsed = time.time() - started
        assert "后台" in out or "bg_" in out
        assert elapsed < 2.0, f"blocked too long: {elapsed}"
        deadline = time.time() + 10
        notes = []
        while time.time() < deadline:
            msgs: list = [{"role": "user", "content": "hi"}]
            n = inject_background_results(msgs)
            if n:
                notes = [msgs[-1]["content"]]
                break
            time.sleep(0.3)
        assert notes, "no task_notification"
        assert "<task_notification>" in notes[0]

    results.append(_case("D01", "D", "bg placeholder + notification", d_bg_placeholder_and_notify))

    def d_fg_waits():
        started = time.time()
        with patch("builtins.input", return_value="y"):
            execute_tool(
                "bash",
                {"command": "ping -n 2 127.0.0.1"},
                BASE_HANDLERS,
                tool_call_id="fg",
            )
        assert time.time() - started >= 0.5

    results.append(_case("D02", "D", "foreground waits", d_fg_waits))

    # ---- E MCP ----
    def e_connect_pool():
        mcp_clients.clear()
        tools, _ = assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)
        names = {t["function"]["name"] for t in tools}
        assert "connect_mcp" in names
        assert not any(n.startswith("mcp__") for n in names)
        connect_mcp("docs")
        tools2, handlers2 = assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)
        names2 = {t["function"]["name"] for t in tools2}
        assert "mcp__docs__search" in names2
        out = handlers2["mcp__docs__search"](query="agent")
        assert "Found" in out or "docs" in out.lower()

    results.append(_case("E01", "E", "connect docs and call search", e_connect_pool))

    def e_deploy_status():
        mcp_clients.clear()
        connect_mcp("deploy")
        _, handlers = assemble_tool_pool(TASK_TOOLS, TOOL_HANDLERS)
        out = handlers["mcp__deploy__status"](service="api")
        assert "running" in out.lower()

    results.append(_case("E02", "E", "deploy status tool", e_deploy_status))

    def e_unknown_server():
        mcp_clients.clear()
        msg = connect_mcp("nope")
        assert "未知" in msg or "Available" in msg

    results.append(_case("E03", "E", "unknown server message", e_unknown_server))

    def e_double_connect():
        mcp_clients.clear()
        first = connect_mcp("docs")
        assert "docs" in first.lower() or "连接" in first
        msg = connect_mcp("docs")
        assert ("已连接" in msg) or ("already" in msg.lower())

    results.append(_case("E04", "E", "idempotent connect", e_double_connect))

    return results
