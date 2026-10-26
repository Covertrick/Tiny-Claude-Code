"""L2：独立子进程。超时杀掉；工作目录锁在沙箱内；网络与越权读由 runner 拒绝。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SandboxResult:
    ok: bool
    output: str
    exit_code: int = 0
    usage: dict = field(default_factory=dict)


def _windows_job_limit(pid: int, mem_mb: int) -> None:
    """尽力把子进程放进 Job，限制内存并在 Job 关闭时杀掉。失败则忽略。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class Ext(ctypes.Structure):
            _fields_ = [
                ("Basic", Basic),
                ("_pad", ctypes.c_byte * 64),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = Ext()
        info.Basic.LimitFlags = 0x00000100 | 0x00002000  # PROCESS_MEMORY | KILL_ON_JOB_CLOSE
        info.ProcessMemoryLimit = int(mem_mb) * 1024 * 1024
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(job, k32.OpenProcess(0x1F0FFF, False, pid))
    except Exception:
        return


def run_process(
    code: str,
    *,
    cwd: Path,
    timeout: float = 5.0,
    mem_mb: int = 128,
) -> SandboxResult:
    cwd = Path(cwd).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    script = cwd / "snippet.py"
    script.write_text(code or "", encoding="utf-8")
    runner = Path(__file__).with_name("runner.py")
    env = os.environ.copy()
    env["SANDBOX_MEM_MB"] = str(mem_mb)
    env["PYTHONNOUSERSITE"] = "1"
    started = time.perf_counter()
    timed_out = False
    proc = subprocess.Popen(
        [sys.executable, "-I", str(runner), str(cwd), str(script)],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _windows_job_limit(proc.pid, mem_mb)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        out, err = proc.communicate()
    elapsed = int((time.perf_counter() - started) * 1000)
    usage = {
        "sandbox": "process",
        "exit_code": int(proc.returncode if proc.returncode is not None else -1),
        "elapsed_ms": elapsed,
        "stdout_bytes": len(out or ""),
        "stderr_bytes": len(err or ""),
        "timed_out": timed_out,
        "mem_mb": mem_mb,
    }
    try:
        (cwd / "trace.json").write_text(
            json.dumps(usage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    text = (out or "").strip()
    if err:
        text = (text + "\n" + err.strip()).strip()
    if timed_out:
        text = (text + "\nsandbox: timeout").strip()
    return SandboxResult(
        ok=proc.returncode == 0 and not timed_out,
        output=text[:4000],
        exit_code=usage["exit_code"],
        usage=usage,
    )
