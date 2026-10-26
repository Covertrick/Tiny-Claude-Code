"""分层执行环境：none 由调用方直接跑；ast=L1；process=L2。"""

from agent.harness.sandbox.ast_sandbox import run_ast
from agent.harness.sandbox.process_sandbox import SandboxResult, run_process

__all__ = ["SandboxResult", "run_ast", "run_process"]
