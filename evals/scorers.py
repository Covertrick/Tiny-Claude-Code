"""断言：文件、工具轨迹、关键字。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def score_case(case: dict, result: dict[str, Any], workspace: Path | None) -> dict:
    """返回 {passed, checks: [{name, ok, detail}]}。"""
    checks = []
    expect = case.get("expect") or {}

    if result.get("error") and not expect.get("allow_error"):
        checks.append({
            "name": "no_crash",
            "ok": False,
            "detail": result["error"],
        })
    else:
        checks.append({"name": "no_crash", "ok": True, "detail": ""})

    if "tools_any" in expect:
        wanted = set(expect["tools_any"])
        got = set(result.get("tool_names") or [])
        ok = bool(wanted & got)
        checks.append({
            "name": "tools_any",
            "ok": ok,
            "detail": f"want∩got={wanted & got}; got={sorted(got)}",
        })

    if "tools_all" in expect:
        wanted = set(expect["tools_all"])
        got = set(result.get("tool_names") or [])
        ok = wanted <= got
        checks.append({
            "name": "tools_all",
            "ok": ok,
            "detail": f"missing={sorted(wanted - got)}; got={sorted(got)}",
        })

    if "tools_none" in expect:
        banned = set(expect["tools_none"])
        got = set(result.get("tool_names") or [])
        hit = banned & got
        checks.append({
            "name": "tools_none",
            "ok": not hit,
            "detail": f"forbidden_used={sorted(hit)}",
        })

    if "output_contains" in expect:
        blob = "\n".join(result.get("tool_outputs") or [])
        blob += "\n" + (result.get("final_text") or "")
        for needle in expect["output_contains"]:
            ok = needle in blob
            checks.append({
                "name": f"output_contains:{needle[:40]}",
                "ok": ok,
                "detail": "found" if ok else "missing",
            })

    if "file_equals" in expect and workspace is not None:
        for rel, content in expect["file_equals"].items():
            path = workspace / rel
            if not path.is_file():
                checks.append({
                    "name": f"file_equals:{rel}",
                    "ok": False,
                    "detail": "file missing",
                })
                continue
            text = path.read_text(encoding="utf-8")
            ok = text == content
            checks.append({
                "name": f"file_equals:{rel}",
                "ok": ok,
                "detail": "match" if ok else f"got={text[:80]!r}",
            })

    if "file_contains" in expect and workspace is not None:
        for rel, needle in expect["file_contains"].items():
            path = workspace / rel
            if not path.is_file():
                checks.append({
                    "name": f"file_contains:{rel}",
                    "ok": False,
                    "detail": "file missing",
                })
                continue
            text = path.read_text(encoding="utf-8")
            ok = needle in text
            checks.append({
                "name": f"file_contains:{rel}",
                "ok": ok,
                "detail": "found" if ok else "missing",
            })

    if "max_elapsed_sec" in expect:
        limit = float(expect["max_elapsed_sec"])
        elapsed = float(result.get("elapsed_sec") or 0)
        ok = elapsed <= limit
        checks.append({
            "name": "max_elapsed_sec",
            "ok": ok,
            "detail": f"{elapsed} <= {limit}",
        })

    passed = all(c["ok"] for c in checks) if checks else False
    return {"passed": passed, "checks": checks}
