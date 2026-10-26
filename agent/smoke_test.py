"""离线冒烟：多租户记忆目录 + 文件沙箱 + 催办 + QQ 工具白名单 + 拦截。"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import agent.config as cfg

# .env 的 load_dotenv(override=True) 之后再盖一层，冒烟强制哈希，避免 HF 卡住
os.environ["QQ_EMBEDDING_BACKEND"] = "hash"
os.environ["QQ_FORCE_SEMANTIC"] = "0"
cfg.FORCE_SEMANTIC = "0"

from agent import user_files as filemod
from agent.embedding import reset_embedder
from agent.knowledge.store import KnowledgeStore, scope_subdir
from agent.schedules.rules import plan_reminder_times
from agent.schedules.store import ScheduleStore

reset_embedder()


def test_knowledge_isolation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = KnowledgeStore(root=root)
        store.kb_add(
            user_id="1001",
            group_id="200",
            text="群200喜欢牛肉面",
            source="group",
            kind="preference",
            title="饮食",
        )
        store.kb_add(
            user_id="1001",
            group_id="300",
            text="群300暗号蓝月亮",
            source="group",
            kind="note",
        )
        store.kb_add(
            user_id="1002",
            group_id="200",
            text="别人的秘密",
            source="group",
        )
        store.kb_add(
            user_id="1001",
            group_id="private",
            text="私聊偏好早起",
            source="private",
            kind="preference",
        )

        # 目录隔离
        assert (root / "group_200" / "memories.jsonl").exists()
        assert (root / "group_300" / "memories.jsonl").exists()
        assert (root / "private_1001" / "memories.jsonl").exists()
        assert scope_subdir("private:1001") == "private_1001"
        assert scope_subdir("group:200") == "group_200"

        group_hits = store.kb_search(user_id="1001", query="牛肉面", group_id="200")
        assert group_hits and any(
            r.group_id == "200" and "牛肉面" in r.text for r, _ in group_hits
        )
        assert all(r.user_id == "1001" and r.group_id in ("200", "private") for r, _ in group_hits)
        assert all(r.scope in ("group:200", "private:1001") for r, _ in group_hits)

        private_hits = store.kb_search(user_id="1001", query="蓝月亮", group_id=None)
        texts = " ".join(r.text for r, _ in private_hits)
        assert "蓝月亮" in texts and "别人的秘密" not in texts
        print("knowledge isolation: OK")


def test_file_scope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old = cfg.FILES_DIR
        cfg.FILES_DIR = root
        filemod.FILES_DIR = root
        try:
            p = filemod.user_dir("1001", "200") / "note.txt"
            p.write_text("hello", encoding="utf-8")
            assert filemod.list_files("1001", "200") == ["note.txt"]
            assert filemod.delete_file("1001", "note.txt", "200")
            assert filemod.list_files("1001", "200") == []
            # 路径穿越
            try:
                filemod.user_dir("1001", "../escape")
                raise AssertionError("应拒绝穿越")
            except ValueError:
                pass
            print("file scope: OK")
        finally:
            cfg.FILES_DIR = old
            filemod.FILES_DIR = old


def test_schedules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "schedules.db"
        store = ScheduleStore(db_path=db)
        due = datetime.now(timezone.utc) + timedelta(days=10)

        parent, ticks = store.create_task_with_reminders(
            user_id="1001",
            group_id="private",
            title="期末考试",
            due_at=due.isoformat(),
            category="exam",
            channel="private",
        )
        assert parent.role == "task"
        assert parent.category == "exam"
        assert len(ticks) >= 2
        labels = {t.label for t in ticks}
        assert "提前一周" in labels or any("周" in x for x in labels)
        assert "提前10分钟" in labels
        assert "提前5小时" in labels
        assert "提前2小时" in labels

        tasks = store.list_for_user(user_id="1001", tasks_only=True)
        assert len(tasks) == 1 and tasks[0].id == parent.id

        meeting_due = datetime.now(timezone.utc) + timedelta(days=5)
        _p2, ticks2 = store.create_task_with_reminders(
            user_id="1001",
            group_id="private",
            title="项目会议",
            due_at=meeting_due.isoformat(),
            category="meeting",
        )
        labs2 = {t.label for t in ticks2}
        assert "提前一天" in labs2
        assert "提前5小时" in labs2
        assert "提前2小时" in labs2

        kids = store.child_ids(parent.id)
        assert store.set_status(user_id="1001", schedule_id=parent.id, status="cancelled")
        for kid in kids:
            assert store.get(kid).status == "cancelled"
        print("schedules: OK")


def test_plan_rules() -> None:
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    due = now + timedelta(days=10)
    exam = plan_reminder_times(category="exam", due_at=due, now=now)
    assert any(l == "提前一周" for l, _ in exam)
    assert any(l == "提前10分钟" for l, _ in exam)
    assert any(l == "提前5小时" for l, _ in exam)
    meet = plan_reminder_times(category="meeting", due_at=due, now=now)
    assert any(l == "提前5小时" for l, _ in meet)
    assert any(l == "提前10分钟" for l, _ in meet)
    assert not any(l == "到点" for l, _ in meet)
    print("plan rules: OK")


def test_group_cache() -> None:
    from agent.channel.group_cache import GroupContextCache

    cache = GroupContextCache(
        maxlen=20, recent_minutes=10, send_limit=5, idle_seconds=3600
    )
    assert not cache.should_store("哈")
    assert not cache.should_store("哈哈哈")
    cache.append("g1", user="张三", text="那个项目怎么搞")
    cache.append("g1", user="李四", text="我今晚要加班")
    snap = cache.snapshot("g1")
    assert "张三" in snap and "加班" in snap
    print("group cache: OK")


def test_intercept() -> None:
    from agent.channel.context import ChatContext
    from agent.channel.intercept import try_intercept
    from agent.channel.session import SESSIONS, session_key

    ctx = ChatContext(user_id="no-such-user", text="待办事项", is_group=False)
    out = try_intercept(ctx)
    assert out is not None and "待办事项" in out
    assert (
        try_intercept(
            ChatContext(user_id="1001", text="帮我搜索天气", is_group=False)
        )
        is None
    )
    # 「退出」只清会话，不杀进程
    uid = "exit-smoke-user"
    skey = session_key(user_id=uid, group_id=None, is_group=False)
    SESSIONS.append(skey, "user", "hi")
    SESSIONS.append(skey, "assistant", "hello")
    reply = try_intercept(
        ChatContext(user_id=uid, text="退出", is_group=False)
    )
    assert reply and "还在线" in reply
    assert SESSIONS.load(skey) == []
    print("intercept: OK")


def test_qq_tool_surface() -> None:
    from agent.channel.context import ChatContext
    from agent.tools.qq import FORBIDDEN_ON_QQ, QQ_TOOL_NAMES, build_tools

    ctx = ChatContext(user_id="1001", text="hi", is_group=False)
    schemas, handlers = build_tools(ctx)
    names = {s["function"]["name"] for s in schemas}
    assert names == set(handlers)
    assert names <= QQ_TOOL_NAMES
    assert not (names & FORBIDDEN_ON_QQ)
    assert "schedule_reminder" in names
    assert "save_memory" in names
    assert "get_memory" in names
    assert "synthesize_knowledge" in names
    assert "list_knowledge_cards" in names
    assert "search_and_send_file" in names
    assert "list_my_files" in names
    assert "kb_add" not in names
    assert "bash" not in names
    assert "edit" not in names
    assert "create_task" not in names
    assert "task" not in names
    print("qq tool surface: OK")


def test_voice_and_files_parse() -> None:
    from agent.channel.message import (
        extract_cache_text,
        extract_file_segments,
        extract_voice_text,
    )

    segs = [
        {"type": "record", "data": {"file": "a.amr", "text": "明天考试别忘了"}},
        {"type": "text", "data": {"text": "补充一句"}},
    ]
    assert extract_voice_text(segs) == "明天考试别忘了"
    assert "明天考试" in extract_cache_text(segs)
    files = extract_file_segments(
        [
            {
                "type": "file",
                "data": {"name": "简历.pdf", "url": "https://example.com/a.pdf"},
            }
        ]
    )
    assert files and files[0]["name"] == "简历.pdf"
    print("voice/files parse: OK")


def test_file_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        from agent.files.index import FileIndexStore

        store = FileIndexStore(db_path=root / "files.db", files_root=root / "groups")
        r = store.add(
            group_id="200",
            uploader_id="1001",
            file_name="简历.pdf",
            local_path=str(root / "groups" / "200" / "简历.pdf"),
            summary="张三提供的候选人简历，用于招聘审核",
            tags="pdf",
        )
        hits = store.search("张三的简历", group_id="200")
        assert hits and hits[0].id == r.id
        assert store.search("别人", group_id="200") == []
        print("file index: OK")


def test_send_chunks() -> None:
    from agent.channel.send import _chunks

    parts = _chunks("第一句。第二句！第三句？还有一行\n末尾")
    assert 1 <= len(parts) <= 3
    assert _chunks("短") == ["短"]
    print("send chunks: OK")


def test_morning_brief() -> None:
    from agent.channel.proactive import build_morning_brief

    # 无主人配置时允许空；有 user 时不炸
    text = build_morning_brief("no-such-owner-xyz")
    assert "早报" in text and "今日待办" in text
    print("morning brief: OK")


def test_concurrency_config() -> None:
    assert cfg.AGENT_CONCURRENCY >= 1
    from agent.channel.router import MessageRouter

    # 不连真实 WS，只检查信号量初始化
    class _Dummy:
        self_id = ""

        def send_group_msg(self, *a, **k):
            pass

        def send_private_msg(self, *a, **k):
            pass

    r = MessageRouter(_Dummy())  # type: ignore[arg-type]
    assert r._sem._value == max(1, cfg.AGENT_CONCURRENCY)
    print("concurrency: OK")


def test_harness_p1() -> None:
    import time

    from agent.harness.effect import RunStatus
    from agent.harness.registry import SkillRegistry, get_skill_registry
    from agent.harness.runtime import get_runtime
    from agent.harness.sandbox.ast_sandbox import run_ast
    from agent.harness.sandbox.process_sandbox import run_process
    from agent.core.execute import execute_tool

    reg = SkillRegistry(Path(__file__).resolve().parents[1] / "plugins")
    reg.scan()
    assert reg.by_package["echo"].status == "indexed"
    assert reg.by_package["echo"].module is None
    assert reg.load("echo") is True
    mod = reg.by_package["echo"].module
    time.sleep(0.18)
    assert len(mod.ticks) >= 1
    assert reg.unload("echo") is True
    time.sleep(0.15)
    stopped = len(mod.ticks)
    time.sleep(0.2)
    assert len(mod.ticks) == stopped

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "plugins"
        bad = root / "bad"
        bad.mkdir(parents=True)
        (bad / "manifest.yaml").write_text(
            "name: bad\nversion: 0.0.1\ntools: [bad_tool]\n",
            encoding="utf-8",
        )
        (bad / "plugin.py").write_text(
            "def register(registry):\n    raise RuntimeError('boom')\n",
            encoding="utf-8",
        )
        broken = SkillRegistry(root)
        broken.scan()
        assert broken.load("bad") is False
        assert broken.by_package["bad"].status == "disabled"

        box = Path(tmp) / "box"
        denied = run_process("open('/etc/passwd').read()", cwd=box)
        assert denied.ok is False
        assert (box / "trace.json").is_file()
        assert denied.usage.get("sandbox") == "process"
        net = run_process(
            "import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=2)",
            cwd=box,
        )
        assert net.ok is False

    ast_ok = run_ast("print(1+1)")
    assert ast_ok.ok and "2" in ast_ok.output
    ast_bad = run_ast("open('/etc/passwd')")
    assert ast_bad.ok is False

    runtime = get_runtime()
    run = runtime.start_run(channel="qq", user_id="p1", group_id=None, text="echo")
    try:
        global_reg = get_skill_registry()
        assert global_reg.refs("echo", "0.1.0") >= 1
        assert global_reg.unload("echo") is False
        frozen = run.skill_snapshot["plugin_echo"]["version"]
        out = execute_tool("plugin_echo", {"text": "hi"}, {})
        assert out == "echo:hi"
        assert run.skill_snapshot["plugin_echo"]["version"] == frozen
    finally:
        runtime.finish(run, status=RunStatus.SUCCEEDED)
    assert get_skill_registry().refs("echo", "0.1.0") == 0
    get_skill_registry().unload("echo")
    print("harness p1: OK")


def test_harness_p2_p3() -> None:
    import agent.config as cfg
    from agent.harness.effect import EffectClass, recovery_for
    from agent.harness.evolve.embodied import EmbodiedSim
    from agent.harness.evolve.loop import propose_and_review, rollback
    from agent.harness.evolve.snapshots import read_text
    from agent.harness.runtime import get_runtime
    from agent.harness.effect import RunStatus
    from agent.harness.trace import harness_rates, trace_for

    sim = EmbodiedSim()
    crashed = sim.grasp("cup", crashed=True)
    assert crashed["recovery"] == recovery_for(EffectClass.IRREVERSIBLE).value
    assert "不确定" in crashed["spoken"]

    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.QQ_RUNTIME
        cfg.QQ_RUNTIME = Path(tmp)
        try:
            before = read_text("guardrails.md")
            bad = propose_and_review("所有技能失败都禁止重试")
            assert bad["action"] == "discard"
            assert read_text("guardrails.md") == before
            good = propose_and_review("不可逆技能结果未知时禁止自动重试，必须询问用户")
            assert good["action"] == "promote"
            assert "禁止自动重试" in read_text("guardrails.md")
            rollback(good["rollback_of"])
            assert "禁止自动重试" not in read_text("guardrails.md")

            from agent.harness.effect import IntentStatus
            from agent.harness.evolve.enforce import postcondition_verdict
            from agent.harness.evolve.snapshots import write_text

            runtime = get_runtime()
            write_text("guardrails.md", "不可逆技能禁止自动重试\n")
            write_text(
                "postconditions.py",
                "def check(result):\n    return 'SECRET' not in str(result)\n",
            )
            held = runtime.start_run(
                channel="qq", user_id="p2b", group_id=None, text="retry"
            )
            first = runtime.begin_intent(held, "send_local_file", {"filename": "a"})
            assert not isinstance(first, str)
            runtime.complete_intent(
                held, first, status=IntentStatus.UNKNOWN, error="crash"
            )
            second = runtime.begin_intent(held, "send_local_file", {"filename": "a"})
            assert isinstance(second, str) and "不确定" in second
            runtime.finish(held, status=RunStatus.UNKNOWN)
            assert postcondition_verdict("hello")[0] is True
            assert postcondition_verdict("SECRET token")[0] is False

            run = runtime.start_run(channel="qq", user_id="p2", group_id=None, text="trace")
            runtime.finish(run, status=RunStatus.SUCCEEDED, reply="ok")
            view = trace_for(run.run_id)
            assert view and view["run_id"] == run.run_id
            rates = harness_rates()
            assert "run_success_rate" in rates
            assert "unknown_rate" in rates
            assert "sandbox_kill_count" in rates
        finally:
            cfg.QQ_RUNTIME = old
    print("harness p2/p3: OK")


def test_search_and_reply_guards() -> None:
    from agent.channel.intent import _regex_gate
    from agent.channel.send import sanitize_user_reply

    assert _regex_gate("搜一下今天天气").memory is False
    assert _regex_gate("你还记得我喜欢什么").memory is True
    kept = sanitize_user_reply("摘要：今天多云，适合出门。")
    assert "多云" in kept
    assert kept != "收到，已归档～"
    short = sanitize_user_reply("已更新记忆")
    assert short == "记好啦 [OK]"
    print("search/reply guards: OK")


def test_web_search_empty_reply() -> None:
    from agent.search import web_search
    from agent.channel.trust import wrap_untrusted

    empty_q = web_search("")
    assert "关键词为空" in empty_q or "补充" in empty_q
    wrapped = wrap_untrusted("web_search", "")
    assert "untrusted_content" in wrapped
    assert wrapped.strip()  # 禁止空串
    print("web search empty reply: OK")


def test_harness_p0() -> None:
    import agent.config as cfg
    from agent.core.execute import execute_tool
    from agent.harness.effect import (
        EffectClass,
        IntentStatus,
        RecoveryAction,
        RunStatus,
        recovery_for,
    )
    from agent.harness.qq_skills import QQ_SKILL_MANIFESTS
    from agent.harness.runtime import HarnessRuntime, current_run
    from agent.harness.store import HarnessStore
    from agent.tools.qq import QQ_TOOL_NAMES

    assert set(QQ_SKILL_MANIFESTS) == set(QQ_TOOL_NAMES)
    assert recovery_for(EffectClass.IDEMPOTENT) is RecoveryAction.RETRY
    assert recovery_for(EffectClass.RETRYABLE) is RecoveryAction.RETRY_SAME_KEY
    assert recovery_for(EffectClass.IRREVERSIBLE) is RecoveryAction.ASK_USER
    assert recovery_for(EffectClass.REQUIRES_CONFIRM) is RecoveryAction.BACK_TO_CONFIRM

    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.QQ_RUNTIME
        cfg.QQ_RUNTIME = Path(tmp)
        try:
            rt = HarnessRuntime(HarnessStore())
            run = rt.start_run(
                channel="qq",
                user_id="1",
                group_id=None,
                text="搜一下",
            )
            assert current_run() is run
            denied = execute_tool("bash", {}, {})
            assert "没有契约" in denied

            out = execute_tool(
                "web_search",
                {"query": "x"},
                {"web_search": lambda query: "结果A"},
            )
            assert out == "结果A"
            assert run.intents[-1].status == IntentStatus.SUCCEEDED.value

            # 模拟执行中崩溃：STARTED 未收口
            crashed = rt.start_run(
                channel="qq", user_id="1", group_id="9", text="发文件"
            )
            intent = rt.begin_intent(crashed, "send_local_file", {"filename": "a.pdf"})
            assert not isinstance(intent, str)
            assert intent.status == IntentStatus.STARTED.value
            # 丢掉内存态，只靠磁盘恢复
            from agent.harness.runtime import _current

            _current.set(None)
            notes = HarnessRuntime(rt.store).recover_open_runs()
            assert notes and "不确定" in notes[0]
            loaded = rt.store.load(crashed.run_id)
            assert loaded is not None
            assert loaded.status == RunStatus.UNKNOWN.value
            assert loaded.intents[0].status == IntentStatus.UNKNOWN.value
            assert loaded.intents[0].recovery == RecoveryAction.ASK_USER.value
            # 再次启动不再重复
            again = HarnessRuntime(rt.store).recover_open_runs()
            assert again == []
            print("harness p0: OK")
        finally:
            cfg.QQ_RUNTIME = old
            from agent.harness.runtime import _current

            _current.set(None)


def test_http_pool() -> None:
    from agent.http_client import http_backend, run_coro

    assert http_backend() in ("httpx", "requests")
    if http_backend() != "httpx":
        print("http pool: SKIP (no httpx)")
        return

    async def _ping():
        return 1 + 1

    assert run_coro(_ping(), timeout=5) == 2
    from agent.core import llm as llm_mod

    assert callable(llm_mod.chat) and callable(llm_mod.chat_async)
    print(f"http pool: OK ({http_backend()})")


def test_vector_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.VECTOR_DIR
        cfg.VECTOR_DIR = Path(tmp)
        try:
            from agent.vector.store import VectorIndex

            idx = VectorIndex("smoke")
            a = [1.0, 0.0, 0.0] + [0.0] * 381
            b = [0.9, 0.1, 0.0] + [0.0] * 381
            c = [0.0, 1.0, 0.0] + [0.0] * 381
            idx.upsert("a", a, meta={"t": "a"})
            idx.upsert("b", b, meta={"t": "b"})
            idx.upsert("c", c, meta={"t": "c"})
            hits = idx.search(a, top_k=2, min_score=0.0)
            assert hits and hits[0][0] in ("a", "b")
            assert idx.count() == 3
            idx.delete("c")
            assert idx.count() == 2
            print(f"vector index: OK ({idx.backend})")
            idx.close()
        finally:
            cfg.VECTOR_DIR = old


if __name__ == "__main__":
    test_knowledge_isolation()
    test_file_scope()
    test_plan_rules()
    test_schedules()
    test_group_cache()
    test_intercept()
    test_qq_tool_surface()
    test_voice_and_files_parse()
    test_file_index()
    test_send_chunks()
    test_morning_brief()
    test_concurrency_config()
    test_harness_p0()
    test_harness_p1()
    test_harness_p2_p3()
    test_search_and_reply_guards()
    test_web_search_empty_reply()
    test_http_pool()
    test_vector_index()
    print("all smoke tests passed")
