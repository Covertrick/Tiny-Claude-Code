"""子进程入口：限制工作目录与网络，再执行用户脚本。由父进程拉起，不要直接当插件用。"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _install_guards(root: Path) -> None:
    import io
    import socket

    def _blocked(*_a, **_k):
        raise PermissionError("sandbox: network disabled")

    socket.socket = _blocked  # type: ignore[misc, assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    if hasattr(socket, "create_server"):
        socket.create_server = _blocked  # type: ignore[assignment]

    real_open = open

    def guarded_open(file, *args, **kwargs):
        path = Path(file)
        if not path.is_absolute():
            path = (root / path).resolve()
        else:
            path = path.resolve()
        if path != root and root not in path.parents:
            raise PermissionError(f"sandbox: path denied {path}")
        return real_open(path, *args, **kwargs)

    import builtins

    builtins.open = guarded_open
    io.open = guarded_open  # type: ignore[assignment]

    if os.name != "nt":
        try:
            import resource

            mem = int(os.environ.get("SANDBOX_MEM_MB", "128")) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: runner.py <root> <script>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    script = Path(sys.argv[2]).resolve()
    if root not in script.parents and script.parent != root:
        print("script outside sandbox", file=sys.stderr)
        return 2
    os.chdir(root)
    source = script.read_text(encoding="utf-8")
    _install_guards(root)
    try:
        exec(compile(source, str(script), "exec"), {"__name__": "__sandbox__"}, None)
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
