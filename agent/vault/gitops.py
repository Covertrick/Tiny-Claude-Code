"""Vault Git 提交 / 可选 push。优先 GitPython，否则 subprocess。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent.config import VAULT_GIT_COMMIT, VAULT_GIT_PUSH
from agent.vault.sync import vault_root


def commit_paths(paths: list[str | Path], message: str) -> str:
    if not VAULT_GIT_COMMIT:
        return "已跳过 Git（QQ_VAULT_GIT_COMMIT=0）"
    root = vault_root()
    if root is None:
        return "Vault 未启用"
    rels: list[str] = []
    for p in paths:
        pp = Path(p)
        if not pp.is_absolute():
            pp = root / pp
        try:
            rels.append(str(pp.resolve().relative_to(root)).replace("\\", "/"))
        except ValueError:
            continue
    if not rels:
        return "没有可提交的文件"
    msg = (message or "chore: vault update").strip()[:200]

    # GitPython
    try:
        import git  # type: ignore

        repo = git.Repo(str(root))
        repo.index.add(rels)
        if not repo.index.diff("HEAD") and not repo.untracked_files:
            # 仍可能刚 add 的在 index
            pass
        repo.index.commit(msg)
        pushed = ""
        if VAULT_GIT_PUSH:
            try:
                origin = repo.remotes.origin
                origin.push()
                pushed = " + pushed"
            except Exception as e:
                pushed = f" （push 失败: {e}）"
        return f"已 commit {len(rels)} 个文件{pushed}"
    except ImportError:
        pass
    except Exception as e:
        return f"GitPython 提交失败: {e}"

    # subprocess 回退
    try:
        subprocess.run(["git", "add", "--", *rels], cwd=str(root), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        if VAULT_GIT_PUSH:
            subprocess.run(
                ["git", "push"],
                cwd=str(root),
                check=False,
                capture_output=True,
            )
        return f"已 commit {len(rels)} 个文件（subprocess）"
    except Exception as e:
        return f"Git 提交跳过/失败: {e}"
