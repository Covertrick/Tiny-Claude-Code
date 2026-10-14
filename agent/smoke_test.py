"""离线冒烟：多租户记忆目录 + 文件沙箱 + 催办 + QQ 工具白名单 + 拦截。"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import agent.config as cfg
from agent import user_files as filemod
from agent.knowledge.store import KnowledgeStore, scope_subdir
from agent.schedules.rules import plan_reminder_times
from agent.schedules.store import ScheduleStore


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
        assert group_hits and all(
            r.group_id == "200" and r.user_id == "1001" for r, _ in group_hits
        )
        assert all(r.scope == "group:200" for r, _ in group_hits)

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
    assert "search_and_send_file" in names
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
    print("all smoke tests passed")
