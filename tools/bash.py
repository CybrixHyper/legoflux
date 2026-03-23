import signal
import subprocess
import os
import sys
from core import error_codes as ec
from core.tool_result import ToolResult
from core.utils import load_config, get_cfg
from core.sandbox import get_workspace_root, validate_bash_command

DEFINITION = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a bash command and return its output. Use this for running scripts, installing packages, or any shell operation.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                }
            },
            "required": ["command"],
        },
    },
}

DANGEROUS_PATTERNS = [
    "rm ", "rm -",
    "rmdir",
    "git push", "git reset", "git clean", "git checkout .",
    "kill ", "killall",
    "chmod", "chown",
    "> /", ">> /",
    "> /dev/", ">> /dev/",
    "-delete",
    "truncate",
    "shred",
    "dd ",
    "mkfs",
    "reboot", "shutdown",
]


def _is_dangerous(command):
    # Best-effort heuristic only.
    # This is NOT a security boundary; workspace sandbox enforcement is.
    cmd = command.strip()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd:
            return True
    return False


def _build_minimal_env(workspace_root):
    """Build a minimal non-secret environment for bash subprocesses."""
    base = {}
    for key in ("PATH", "LANG", "LC_ALL", "TZ", "TERM", "TMPDIR", "USER", "LOGNAME", "SHELL"):
        val = os.environ.get(key)
        if val:
            base[key] = val
    base["HOME"] = workspace_root
    base["PWD"] = workspace_root
    return base


def execute(arguments):
    command = arguments["command"]

    cfg = load_config()
    if get_cfg(cfg, "runtime.bash_safe_mode", True) and _is_dangerous(command):
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return ToolResult.error(
                ec.SANDBOX_BLOCKED,
                "Dangerous command blocked in non-interactive mode (requires TTY confirmation).",
            )
        print(f"\n  ⚠ Dangerous command: {command}")
        try:
            answer = input("  Allow? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ToolResult.error(
                ec.INTERRUPTED,
                "Command blocked (confirmation interrupted).",
            )
        if answer != "y":
            return ToolResult.error(ec.BLOCKED_BY_USER, "Command blocked by user.")
    sandbox_err = validate_bash_command(command, cfg)
    if sandbox_err:
        return sandbox_err

    workspace_root = get_workspace_root(cfg)
    timeout_sec = int(get_cfg(cfg, "runtime.bash_timeout_sec", 30))
    bash_env = _build_minimal_env(workspace_root)

    try:
        proc = subprocess.Popen(
            ["bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workspace_root,
            env=bash_env,
            start_new_session=True,
        )
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        output = stdout or ""

        if proc.returncode != 0:
            output += f"\nSTDERR:\n{stderr}" if stderr else ""
            output += f"\nExit code: {proc.returncode}"
        return ToolResult.success(
            output if output else "(no output)",
            exit_code=int(proc.returncode),
        )
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            stdout, stderr = proc.communicate()
        output = stdout or ""
        if stderr:
            output += f"\nSTDERR:\n{stderr}"
        return ToolResult.error(
            ec.TIMEOUT,
            f"command timed out after {timeout_sec} seconds",
            content=f"Error: command timed out after {timeout_sec} seconds\n{output}".rstrip(),
            timeout_sec=timeout_sec,
        )
    except Exception as e:
        return ToolResult.error(ec.EXEC_FAILED, str(e))
