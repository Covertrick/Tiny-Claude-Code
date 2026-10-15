"""Dashboard CRUD API：记忆 / 待办 / Vault，预览与下载，直接落库。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response


def _qq(user: dict) -> str:
    qq = str(user.get("qq") or "").strip()
    if not qq:
        raise HTTPException(401, "无用户身份")
    return qq


def _mem_dict(r, *, full: bool = False) -> dict[str, Any]:
    text = r.text or ""
    return {
        "id": r.id,
        "title": r.title or "",
        "kind": r.kind,
        "layer": r.layer,
        "group_id": r.group_id,
        "source": r.source,
        "created_at": r.created_at,
        "archived": bool(r.archived),
        "text": text if full else text[:240],
        "text_full": text if full else None,
    }


def _sched_dict(s) -> dict[str, Any]:
    return {
        "id": s.id,
        "title": s.title,
        "category": getattr(s, "category", "todo"),
        "status": s.status,
        "due_at": s.due_at,
        "remind_at": getattr(s, "remind_at", None),
        "role": getattr(s, "role", "task"),
        "group_id": getattr(s, "group_id", "private"),
        "channel": getattr(s, "channel", "private"),
    }


def build_crud_router(require_user: Callable) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["crud"])

    # ========== 记忆 ==========
    @router.get("/knowledge")
    def list_knowledge(
        user: dict = Depends(require_user),
        q: str = Query(""),
        limit: int = Query(50),
    ):
        from agent.knowledge import get_knowledge_store

        kb = get_knowledge_store()
        qq = _qq(user)
        if q.strip():
            hits = kb.kb_search(
                user_id=qq, query=q.strip(), group_id=None, top_k=limit, min_score=0.0
            )
            return {
                "items": [
                    {**_mem_dict(r), "score": score} for r, score in hits
                ]
            }
        return {"items": [_mem_dict(r) for r in kb.list_for_user(user_id=qq, limit=limit)]}

    @router.get("/knowledge/{mid}")
    def get_knowledge(mid: str, user: dict = Depends(require_user)):
        from agent.knowledge import get_knowledge_store

        r = get_knowledge_store().get(user_id=_qq(user), memory_id=mid)
        if not r:
            raise HTTPException(404, "记忆不存在")
        return _mem_dict(r, full=True)

    @router.get("/knowledge/{mid}/download")
    def download_knowledge(mid: str, user: dict = Depends(require_user)):
        from agent.knowledge import get_knowledge_store

        r = get_knowledge_store().get(user_id=_qq(user), memory_id=mid)
        if not r:
            raise HTTPException(404, "记忆不存在")
        body = (
            f"---\nid: {r.id}\ntitle: {r.title or ''}\nkind: {r.kind}\n"
            f"layer: {r.layer}\ngroup_id: {r.group_id}\ncreated: {r.created_at}\n"
            f"---\n\n{r.text or ''}\n"
        )
        name = quote(f"memory-{r.id}.md")
        return Response(
            content=body.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
        )

    @router.post("/knowledge")
    def create_knowledge(body: dict, user: dict = Depends(require_user)):
        from agent.knowledge import get_knowledge_store

        text = str((body or {}).get("text") or "").strip()
        if not text:
            raise HTTPException(400, "text 不能为空")
        title = str((body or {}).get("title") or "").strip()
        kind = str((body or {}).get("kind") or "note").strip()
        layer = str((body or {}).get("layer") or "episodic").strip()
        group_id = str((body or {}).get("group_id") or "private").strip() or "private"
        r = get_knowledge_store().remember(
            user_id=_qq(user),
            group_id=group_id,
            text=text,
            source="dashboard",
            kind=kind,
            title=title,
            layer=layer,
        )
        return {"ok": True, "item": _mem_dict(r, full=True)}

    @router.put("/knowledge/{mid}")
    def update_knowledge(mid: str, body: dict, user: dict = Depends(require_user)):
        from agent.knowledge import get_knowledge_store

        r = get_knowledge_store().update_record(
            memory_id=mid,
            user_id=_qq(user),
            text=(body or {}).get("text"),
            title=(body or {}).get("title"),
            kind=(body or {}).get("kind"),
            layer=(body or {}).get("layer"),
        )
        if not r:
            raise HTTPException(404, "记忆不存在")
        return {"ok": True, "item": _mem_dict(r, full=True)}

    @router.delete("/knowledge/{mid}")
    def delete_knowledge(mid: str, user: dict = Depends(require_user)):
        from agent.knowledge import get_knowledge_store

        ok = get_knowledge_store().delete(user_id=_qq(user), memory_id=mid)
        if not ok:
            raise HTTPException(404, "记忆不存在")
        return {"ok": True, "id": mid}

    # ========== 待办 ==========
    @router.get("/schedules")
    def list_schedules(user: dict = Depends(require_user)):
        from agent.schedules import get_schedule_store

        items = get_schedule_store().list_for_user(
            user_id=_qq(user), tasks_only=True, include_done=True
        )[:100]
        return {"items": [_sched_dict(s) for s in items]}

    @router.get("/schedules/{sid}")
    def get_schedule(sid: str, user: dict = Depends(require_user)):
        from agent.schedules import get_schedule_store

        s = get_schedule_store().get(sid)
        if not s or str(s.user_id) != _qq(user):
            raise HTTPException(404, "任务不存在")
        return _sched_dict(s)

    @router.post("/schedules")
    def create_schedule(body: dict, user: dict = Depends(require_user)):
        from agent.schedules import get_schedule_store
        from agent.scheduler import get_reminder_scheduler

        title = str((body or {}).get("title") or "").strip()
        due_at = str((body or {}).get("due_at") or "").strip()
        if not title or not due_at:
            raise HTTPException(400, "需要 title 与 due_at（ISO8601）")
        category = str((body or {}).get("category") or "todo").strip() or "todo"
        qq = _qq(user)
        parent = get_schedule_store().create(
            user_id=qq,
            group_id="private",
            title=title,
            due_at=due_at,
            category=category,
            channel="private",
        )
        try:
            sched = get_reminder_scheduler()
            if sched:
                sched.reload_upcoming()
        except Exception:
            pass
        return {"ok": True, "item": _sched_dict(parent)}

    @router.put("/schedules/{sid}")
    def update_schedule(sid: str, body: dict, user: dict = Depends(require_user)):
        from agent.schedules import get_schedule_store

        s = get_schedule_store().update_task(
            user_id=_qq(user),
            schedule_id=sid,
            title=(body or {}).get("title"),
            due_at=(body or {}).get("due_at"),
            category=(body or {}).get("category"),
        )
        if not s:
            raise HTTPException(404, "任务不存在")
        status = (body or {}).get("status")
        if status in ("pending", "done", "cancelled"):
            get_schedule_store().set_status(
                user_id=_qq(user), schedule_id=sid, status=status
            )
            s = get_schedule_store().get(sid)
        return {"ok": True, "item": _sched_dict(s)}

    @router.post("/schedules/{sid}/status")
    def schedule_status(sid: str, body: dict, user: dict = Depends(require_user)):
        from agent.schedules import get_schedule_store
        from agent.scheduler import get_reminder_scheduler

        status = str((body or {}).get("status") or "").strip()
        if status not in ("pending", "done", "cancelled"):
            raise HTTPException(400, "status 须为 pending|done|cancelled")
        store = get_schedule_store()
        qq = _qq(user)
        ok = store.set_status(user_id=qq, schedule_id=sid, status=status)
        if ok and status in ("done", "cancelled"):
            try:
                sched = get_reminder_scheduler()
                if sched:
                    sched.disarm(sid)
                    for kid in store.child_ids(sid):
                        sched.disarm(kid)
            except Exception:
                pass
        return {"ok": bool(ok), "id": sid, "status": status}

    @router.delete("/schedules/{sid}")
    def delete_schedule(sid: str, user: dict = Depends(require_user)):
        from agent.schedules import get_schedule_store
        from agent.scheduler import get_reminder_scheduler

        store = get_schedule_store()
        qq = _qq(user)
        try:
            sched = get_reminder_scheduler()
            if sched:
                sched.disarm(sid)
                for kid in store.child_ids(sid):
                    sched.disarm(kid)
        except Exception:
            pass
        ok = store.delete(user_id=qq, schedule_id=sid)
        if not ok:
            raise HTTPException(404, "任务不存在")
        return {"ok": True, "id": sid}

    @router.get("/schedules/{sid}/download")
    def download_schedule(sid: str, user: dict = Depends(require_user)):
        from agent.schedules import get_schedule_store

        s = get_schedule_store().get(sid)
        if not s or str(s.user_id) != _qq(user):
            raise HTTPException(404, "任务不存在")
        payload = json.dumps(_sched_dict(s), ensure_ascii=False, indent=2)
        return Response(
            content=payload.encode("utf-8"),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=schedule-{sid}.json"
            },
        )

    # ========== Vault ==========
    @router.get("/vault")
    def list_vault(user: dict = Depends(require_user), q: str = Query("")):
        _qq(user)
        from agent.vault.index import get_vault_index
        from agent.vault.sync import vault_enabled

        if not vault_enabled():
            return {
                "enabled": False,
                "files": [],
                "hits": [],
                "graph": {"nodes": [], "edges": []},
            }
        idx = get_vault_index()
        hits = []
        if q.strip():
            hits = [
                {
                    "path": h.path,
                    "title": h.title,
                    "score": h.score,
                    "chunk": h.chunk[:200],
                    "tags": h.tags,
                }
                for h in idx.search(q.strip(), top_k=12)
            ]
        return {
            "enabled": True,
            "stats": idx.stats(),
            "files": idx.list_files(limit=100),
            "hits": hits,
            "graph": idx.graph_edges(limit_nodes=36),
        }

    @router.get("/vault/file")
    def preview_vault_file(
        path: str = Query(...),
        user: dict = Depends(require_user),
    ):
        _qq(user)
        from agent.vault.sync import safe_vault_path, vault_enabled

        if not vault_enabled():
            raise HTTPException(400, "Vault 未启用")
        try:
            p = safe_vault_path(path)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not p.is_file():
            raise HTTPException(404, "文件不存在")
        text = p.read_text(encoding="utf-8", errors="replace")
        return {
            "path": path.replace("\\", "/"),
            "title": p.stem,
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "content": text,
        }

    @router.get("/vault/file/download")
    def download_vault_file(
        path: str = Query(...),
        user: dict = Depends(require_user),
    ):
        _qq(user)
        from agent.vault.sync import safe_vault_path, vault_enabled

        if not vault_enabled():
            raise HTTPException(400, "Vault 未启用")
        try:
            p = safe_vault_path(path)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not p.is_file():
            raise HTTPException(404, "文件不存在")
        data = p.read_bytes()
        name = quote(p.name)
        return Response(
            content=data,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
        )

    @router.post("/vault/file")
    def create_vault_file(body: dict, user: dict = Depends(require_user)):
        _qq(user)
        from agent.config import VAULT_NOTES_SUBDIR
        from agent.vault.gitops import commit_paths
        from agent.vault.sync import index_file, safe_vault_path, vault_enabled

        if not vault_enabled():
            raise HTTPException(400, "Vault 未启用：请配置 QQ_VAULT_PATH")
        content = str((body or {}).get("content") or "")
        rel = str((body or {}).get("path") or "").strip()
        title = str((body or {}).get("title") or "untitled").strip() or "untitled"
        if not rel:
            day = datetime.now().strftime("%Y-%m-%d")
            safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in title)[:40]
            rel = f"{VAULT_NOTES_SUBDIR}/{day}-{safe or 'note'}.md"
        if not rel.lower().endswith(".md"):
            rel += ".md"
        try:
            target = safe_vault_path(rel)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if target.exists():
            raise HTTPException(409, f"已存在: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        idx = index_file(target)
        git = commit_paths([target], f"docs: dashboard create {title[:40]}")
        return {
            "ok": True,
            "path": rel.replace("\\", "/"),
            "index": idx,
            "git": git,
        }

    @router.put("/vault/file")
    def update_vault_file(body: dict, user: dict = Depends(require_user)):
        _qq(user)
        from agent.vault.gitops import commit_paths
        from agent.vault.sync import index_file, safe_vault_path, vault_enabled

        if not vault_enabled():
            raise HTTPException(400, "Vault 未启用")
        rel = str((body or {}).get("path") or "").strip()
        content = (body or {}).get("content")
        if not rel or content is None:
            raise HTTPException(400, "需要 path 与 content")
        try:
            target = safe_vault_path(rel)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not target.is_file():
            raise HTTPException(404, "文件不存在")
        target.write_text(str(content), encoding="utf-8")
        idx = index_file(target)
        git = commit_paths([target], f"docs: dashboard edit {rel}")
        return {"ok": True, "path": rel.replace("\\", "/"), "index": idx, "git": git}

    @router.delete("/vault/file")
    def delete_vault_file(
        path: str = Query(...),
        user: dict = Depends(require_user),
    ):
        _qq(user)
        from agent.vault.gitops import commit_paths
        from agent.vault.sync import remove_indexed, safe_vault_path, vault_enabled

        if not vault_enabled():
            raise HTTPException(400, "Vault 未启用")
        try:
            target = safe_vault_path(path)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not target.is_file():
            raise HTTPException(404, "文件不存在")
        target.unlink()
        remove_indexed(path)
        git = commit_paths([], f"docs: dashboard delete {path}")
        # git delete: add deletion
        try:
            from agent.vault.sync import vault_root
            import subprocess

            root = vault_root()
            if root:
                subprocess.run(
                    ["git", "rm", "-f", "--", path.replace("\\", "/")],
                    cwd=str(root),
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", f"docs: dashboard delete {path}"],
                    cwd=str(root),
                    capture_output=True,
                )
                git = "已 git rm + commit"
        except Exception:
            pass
        return {"ok": True, "path": path, "git": git}

    return router
