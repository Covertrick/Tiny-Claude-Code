"""评测入口：offline / online / all。

用法:
  python -m evals.runner --mode offline
  python -m evals.runner --mode online --skip-f --token-budget 120000
  python -m evals.runner --mode all --token-budget 180000
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from evals.budget import BUDGET
from evals.harness import load_json_cases, run_agent_once, temporary_workspace
from evals.offline_suite import run_offline
from evals.scorers import score_case

CASES_DIR = Path(__file__).resolve().parent / "cases"
REPORT_DIR = Path(__file__).resolve().parent / "reports"


def _load_online_cases(categories: set[str] | None, skip_f: bool) -> list[dict]:
    files = sorted(CASES_DIR.glob("*.json"))
    cases = []
    for path in files:
        for case in load_json_cases(path):
            cat = case.get("category", "?")
            if skip_f and cat == "F":
                continue
            if categories and cat not in categories:
                continue
            if case.get("mode", "online") != "online":
                continue
            cases.append(case)
    return cases


def _apply_setup(workspace: Path, case: dict) -> None:
    for rel, content in (case.get("setup_files") or {}).items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_online(
    categories: set[str] | None,
    skip_f: bool,
    token_budget: int,
    case_ids: set[str] | None,
) -> list[dict]:
    cases = _load_online_cases(categories, skip_f)
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]

    spent = 0
    results = []
    for case in cases:
        est = int(case.get("est_tokens") or 3000)
        if spent + est > token_budget:
            results.append({
                "id": case["id"],
                "category": case.get("category"),
                "name": case.get("prompt", "")[:40],
                "mode": "online",
                "passed": False,
                "detail": f"skipped: would exceed token budget ({spent}+{est}>{token_budget})",
                "usage": {"total_tokens": 0},
                "skipped": True,
            })
            continue

        print(f"\n=== ONLINE {case['id']} (est {est}, spent {spent}/{token_budget}) ===")
        with temporary_workspace(prefix=f"eval-{case['id']}-") as workspace:
            _apply_setup(workspace, case)
            # 清空 MCP 连接，避免跨题污染
            from agent.mcp.connect import mcp_clients
            mcp_clients.clear()

            auto = case.get("auto_approve", True)
            raw = run_agent_once(case["prompt"], auto_approve=auto)
            scored = score_case(case, raw, workspace)
            used = int((raw.get("usage") or {}).get("total_tokens") or 0)
            if used == 0:
                # API 未返回 usage 时用估算计入预算，避免超支
                used = est
            spent += used
            results.append({
                "id": case["id"],
                "category": case.get("category"),
                "name": case.get("prompt", "")[:60],
                "mode": "online",
                "passed": scored["passed"],
                "detail": json.dumps(scored["checks"], ensure_ascii=False)[:500],
                "usage": raw.get("usage") or {"total_tokens": used},
                "elapsed_sec": raw.get("elapsed_sec"),
                "error": raw.get("error"),
                "tool_names": raw.get("tool_names"),
                "skipped": False,
            })
            status = "PASS" if scored["passed"] else "FAIL"
            print(f"  -> {status} tokens~{used} tools={raw.get('tool_names')}")
    return results


def summarize(results: list[dict]) -> dict:
    by_cat: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "passed": 0, "failed": 0, "skipped": 0, "tokens": 0
    })
    for r in results:
        cat = r.get("category") or "?"
        by_cat[cat]["total"] += 1
        if r.get("skipped"):
            by_cat[cat]["skipped"] += 1
        elif r.get("passed"):
            by_cat[cat]["passed"] += 1
        else:
            by_cat[cat]["failed"] += 1
        by_cat[cat]["tokens"] += int((r.get("usage") or {}).get("total_tokens") or 0)

    overall = {
        "total": len(results),
        "passed": sum(1 for r in results if r.get("passed") and not r.get("skipped")),
        "failed": sum(1 for r in results if not r.get("passed") and not r.get("skipped")),
        "skipped": sum(1 for r in results if r.get("skipped")),
        "tokens": sum(int((r.get("usage") or {}).get("total_tokens") or 0) for r in results),
        "by_category": dict(by_cat),
    }
    return overall


def write_report(results: list[dict], summary: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"report_{stamp}.json"
    payload = {
        "budget_plan": BUDGET,
        "summary": summary,
        "results": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = REPORT_DIR / f"report_{stamp}.md"
    lines = [
        f"# Eval Report {stamp}",
        "",
        f"- passed: **{summary['passed']}** / failed: {summary['failed']} / "
        f"skipped: {summary['skipped']} / total: {summary['total']}",
        f"- tokens (reported/estimated): **{summary['tokens']}**",
        "",
        "| Cat | Pass | Fail | Skip | Tokens |",
        "|-----|------|------|------|--------|",
    ]
    for cat, row in sorted(summary["by_category"].items()):
        lines.append(
            f"| {cat} | {row['passed']} | {row['failed']} | "
            f"{row['skipped']} | {row['tokens']} |"
        )
    lines.append("")
    lines.append("## Cases")
    for r in results:
        mark = "SKIP" if r.get("skipped") else ("PASS" if r.get("passed") else "FAIL")
        lines.append(f"- `{r['id']}` [{r.get('category')}] **{mark}** — {r.get('detail','')[:120]}")
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny-Claude-Code evals")
    parser.add_argument(
        "--mode",
        choices=["offline", "online", "all"],
        default="offline",
    )
    parser.add_argument("--skip-f", action="store_true", help="跳过昂贵的 F 类")
    parser.add_argument(
        "--token-budget",
        type=int,
        default=BUDGET["hard_cap_default"],
        help="在线题 token 硬顶（默认 18 万）",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default="",
        help="逗号分隔，如 A,B,E；空=全部",
    )
    parser.add_argument("--ids", type=str, default="", help="只跑指定 case id")
    args = parser.parse_args()

    cats = {c.strip().upper() for c in args.categories.split(",") if c.strip()} or None
    ids = {i.strip() for i in args.ids.split(",") if i.strip()} or None

    results: list[dict] = []
    if args.mode in ("offline", "all"):
        print(">>> OFFLINE (0 token)")
        results.extend(run_offline())
    if args.mode in ("online", "all"):
        print(">>> ONLINE")
        results.extend(
            run_online(
                categories=cats,
                skip_f=args.skip_f,
                token_budget=args.token_budget,
                case_ids=ids,
            )
        )

    summary = summarize(results)
    report = write_report(results, summary)
    print("\n========== SUMMARY ==========")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
