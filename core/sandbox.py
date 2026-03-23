import os
import re
import shlex
from typing import Optional, Tuple

from core import error_codes as ec
from core.tool_result import ToolResult
from core.utils import get_cfg, load_config


_SECOND_STAGE_EXEC_RE = re.compile(
    r"(^|[|;&])\s*"
    r"(bash|sh|zsh|fish|dash|ksh|python|python3|node|ruby|perl)"
    r"\s+(-c|-lc|-ic|-e)\b",
    re.IGNORECASE,
)

_CHAINED_INTERPRETER_RE = re.compile(
    r"([|;&]|&&|\|\|)\s*"
    r"(bash|sh|zsh|fish|dash|ksh|python|python3|node|ruby|perl)\b",
    re.IGNORECASE,
)


def _within_workspace(path: str, workspace_root: str) -> bool:
    try:
        return os.path.commonpath([path, workspace_root]) == workspace_root
    except ValueError:
        return False


def _sandbox_error(message: str, reason: str, **meta) -> ToolResult:
    return ToolResult.error(
        ec.SANDBOX_BLOCKED,
        message,
        content=f"Error: {message}",
        reason=reason,
        **meta,
    )


def _not_found_error(message: str, expected: str, **meta) -> ToolResult:
    return ToolResult.error(
        ec.NOT_FOUND,
        message,
        content=f"Error: {message}",
        expected=expected,
        **meta,
    )


def _invalid_args_error(message: str, expected: str, **meta) -> ToolResult:
    return ToolResult.error(
        ec.INVALID_ARGS,
        message,
        content=f"Error: {message}",
        expected=expected,
        **meta,
    )


def is_workspace_sandbox_enabled(cfg=None) -> bool:
    cfg = cfg or load_config()
    return bool(get_cfg(cfg, "runtime.workspace_sandbox_enabled", True))


def get_workspace_root(cfg=None) -> str:
    cfg = cfg or load_config()
    root = str(get_cfg(cfg, "runtime.workspace_root", ".") or ".")
    if not os.path.isabs(root):
        root = os.path.join(os.getcwd(), root)
    return os.path.realpath(os.path.abspath(root))


def resolve_path(path: str, cfg=None) -> Tuple[Optional[str], Optional[ToolResult]]:
    """Resolve path with sandbox check. Returns (resolved_path, ToolResult|None)."""
    cfg = cfg or load_config()
    workspace_root = get_workspace_root(cfg)
    if os.path.isabs(path):
        resolved = os.path.realpath(os.path.abspath(path))
    else:
        resolved = os.path.realpath(os.path.abspath(os.path.join(workspace_root, path)))

    if is_workspace_sandbox_enabled(cfg) and not _within_workspace(resolved, workspace_root):
        err = _sandbox_error(f"Path escapes workspace sandbox: {path}", reason="path_escape", path=path)
        return None, err
    return resolved, None


def resolve_file(path: str) -> Tuple[Optional[str], Optional[ToolResult]]:
    """Resolve + require existing file. Returns (resolved, None) or (None, ToolResult)."""
    resolved, err = resolve_path(path)
    if err:
        return None, err
    if not os.path.exists(resolved):
        return None, _not_found_error(f"File not found: {path}", expected="file", path=path)
    if os.path.isdir(resolved):
        return None, _invalid_args_error(f"Path is a directory, not a file: {path}", expected="file", path=path)
    return resolved, None


def resolve_dir(path: str) -> Tuple[Optional[str], Optional[ToolResult]]:
    """Resolve + require existing directory. Returns (resolved, None) or (None, ToolResult)."""
    resolved, err = resolve_path(path)
    if err:
        return None, err
    if not os.path.exists(resolved):
        return None, _not_found_error(f"Path not found: {path}", expected="directory", path=path)
    if not os.path.isdir(resolved):
        return None, _invalid_args_error(f"Not a directory: {path}", expected="directory", path=path)
    return resolved, None


def validate_bash_command(command: str, cfg=None) -> Optional[ToolResult]:
    cfg = cfg or load_config()
    if not is_workspace_sandbox_enabled(cfg):
        return None

    workspace_root = get_workspace_root(cfg)
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens:
        return None

    if any(marker in command for marker in ("`", "$(", "<(", ">(")):
        return _sandbox_error(
            "command blocked by workspace sandbox (command/process substitution not allowed)",
            reason="cmd_substitution",
        )

    # Block second-stage interpreters anywhere in chained shell commands.
    if _SECOND_STAGE_EXEC_RE.search(command):
        return _sandbox_error(
            "command blocked by workspace sandbox (second-stage interpreter execution not allowed)",
            reason="second_stage_interpreter",
        )
    if _CHAINED_INTERPRETER_RE.search(command):
        return _sandbox_error(
            "command blocked by workspace sandbox (chained interpreter execution not allowed)",
            reason="chained_interpreter",
        )

    for token in tokens:
        candidate = token.lstrip("0123456789<>")
        if not candidate:
            continue

        if candidate == ".." or candidate.startswith("../") or "/../" in candidate or candidate.endswith("/.."):
            return _sandbox_error(
                "command blocked by workspace sandbox (parent traversal not allowed)",
                reason="parent_traversal",
                candidate=candidate,
            )

        if candidate == "~" or candidate.startswith("~/"):
            return _sandbox_error(
                "command blocked by workspace sandbox (home directory access not allowed)",
                reason="home_access",
                candidate=candidate,
            )

        if candidate.startswith("/"):
            resolved = os.path.realpath(os.path.abspath(candidate))
            if not _within_workspace(resolved, workspace_root):
                return _sandbox_error(
                    f"command blocked by workspace sandbox (outside workspace): {candidate}",
                    reason="outside_workspace",
                    candidate=candidate,
                )

    return None
