"""FastAPI 控制面：metrics + Magic Link Dashboard。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

_STATIC = Path(__file__).resolve().parent / "static"


def start_admin_thread(port: int) -> None:
    import uvicorn
    from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    from agent.admin.auth import (
        build_magic_link,
        cookie_secure_for_base,
        issue_magic_token,
        public_base_url,
        verify_magic_token,
    )
    from agent.admin.metrics import snapshot_metrics
    from agent.config import ADMIN_MAGIC_TTL

    app = FastAPI(title="Tiny QQ Agent Admin", version="0.4.0")
    if _STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    SESSION_COOKIE = "qq_admin_sess"

    def _set_session(resp: Response, qq: str) -> None:
        token = issue_magic_token(user_qq=qq)
        secure = cookie_secure_for_base()
        resp.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=ADMIN_MAGIC_TTL,
            httponly=True,
            samesite="none" if secure else "lax",
            secure=secure,
        )

    def require_owner(
        token: str | None = Query(None),
        sess: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> dict:
        raw = token or sess
        if not raw:
            raise HTTPException(401, "需要 Magic Link 登录")
        try:
            return verify_magic_token(raw)
        except Exception as e:
            raise HTTPException(401, f"登录失效：{e}") from e

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/metrics")
    def metrics(_: dict = Depends(require_owner)):
        return snapshot_metrics()

    @app.get("/plugins")
    def plugins(_: dict = Depends(require_owner)):
        try:
            from plugins.loader import get_registry

            return {
                name: {
                    "version": p.version,
                    "description": p.description,
                    "enabled": p.enabled,
                }
                for name, p in get_registry().plugins.items()
            }
        except Exception as e:
            return {"error": str(e)}

    @app.post("/plugins/{name}/reload")
    def reload(name: str, _: dict = Depends(require_owner)):
        from plugins.loader import reload_plugin

        return {"name": name, "ok": reload_plugin(name)}

    @app.get("/harness/runs")
    def harness_runs(_: dict = Depends(require_owner)):
        from agent.harness.trace import list_traces

        return {"runs": list_traces()}

    @app.get("/harness/runs/{run_id}")
    def harness_trace(run_id: str, _: dict = Depends(require_owner)):
        from agent.harness.trace import trace_for

        data = trace_for(run_id)
        if data is None:
            raise HTTPException(404, "run 不存在")
        return data

    @app.get("/sessions")
    def sessions(_: dict = Depends(require_owner)):
        try:
            from agent.channel.session import SESSIONS

            data = getattr(SESSIONS, "_data", None) or getattr(SESSIONS, "cache", {})
            if isinstance(data, dict):
                return {"count": len(data), "keys": list(data.keys())[:50]}
            return {"count": 0, "keys": []}
        except Exception as e:
            return {"error": str(e)}

    # —— Dashboard ——
    @app.get("/")
    def root():
        return RedirectResponse("/dash")

    @app.get("/dash")
    def dash(token: str | None = Query(None)):
        html_path = _STATIC / "dashboard.html"
        if not html_path.is_file():
            return HTMLResponse("<h1>dashboard.html missing</h1>", status_code=500)
        if token:
            try:
                data = verify_magic_token(token)
                resp = RedirectResponse("/dash", status_code=302)
                _set_session(resp, str(data.get("qq") or ""))
                return resp
            except Exception as e:
                return HTMLResponse(
                    f"<h1>Magic Link 无效或过期</h1><p>{e}</p>"
                    f"<p>请私聊机器人重新发送「打开控制台」。</p>",
                    status_code=401,
                )
        return FileResponse(html_path, media_type="text/html")

    @app.get("/api/me")
    def me(user: dict = Depends(require_owner)):
        from agent.vault.sync import vault_enabled, vault_root
        from agent.vault.index import get_vault_index

        vault = {"enabled": vault_enabled(), "path": None, "stats": {}}
        if vault_enabled():
            vault["path"] = str(vault_root())
            vault["stats"] = get_vault_index().stats()
        return {
            "qq": user.get("qq"),
            "role": user.get("role"),
            "vault": vault,
            "ttl": ADMIN_MAGIC_TTL,
        }

    from agent.admin.crud import build_crud_router

    app.include_router(build_crud_router(require_owner))

    @app.get("/api/magic/issue")
    def issue_link(user: dict = Depends(require_owner)):
        try:
            url = build_magic_link(user_qq=str(user.get("qq") or ""), port=port)
            return {"url": url, "ttl": ADMIN_MAGIC_TTL}
        except Exception as e:
            raise HTTPException(400, str(e)) from e

    from agent.admin.auth import public_host
    from agent.config import ADMIN_BIND, ADMIN_TUNNEL

    bind = ADMIN_BIND or "0.0.0.0"

    def _run() -> None:
        uvicorn.run(app, host=bind, port=port, log_level="warning")

    threading.Thread(target=_run, name="admin-api", daemon=True).start()
    if ADMIN_TUNNEL not in ("off", "0", "false", "no", "none"):
        try:
            from agent.admin.tunnel import start_admin_tunnel_async

            start_admin_tunnel_async(port)
            print("[tunnel] 正在后台建立公网隧道…")
        except Exception as e:
            print(f"[tunnel] 未能启动: {e}")
    lan = public_host()
    print(
        f"[admin] bind={bind}:{port} "
        f"本机 http://127.0.0.1:{port}/dash "
        f"局域网 http://{lan}:{port}/dash "
        f"| 公网地址就绪后「打开控制台」会自动用 https"
    )
