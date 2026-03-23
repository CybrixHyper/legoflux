"""Structured tool execution result."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str
    error_code: Optional[str] = None
    message: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def success(content: str, **meta) -> "ToolResult":
        return ToolResult(ok=True, content=str(content), meta=meta)

    @staticmethod
    def error(code: str, message: str, content: str = "", **meta) -> "ToolResult":
        visible = str(content or f"Error: {message}")
        return ToolResult(
            ok=False,
            content=visible,
            error_code=str(code),
            message=str(message),
            meta=meta,
        )


def tool_exec_error(code: str, err: Any, **meta) -> ToolResult:
    return ToolResult.error(code, str(err), **meta)


def limited_lines_output(lines: Sequence[str], limit: int, notice_template: str) -> Tuple[str, int, bool]:
    total = len(lines)
    if total > limit:
        body = "\n".join(lines[:limit])
        notice = notice_template.format(limit=limit, total=total, next_limit=limit * 2)
        return f"{body}\n\n{notice}", total, True
    return "\n".join(lines), total, False
