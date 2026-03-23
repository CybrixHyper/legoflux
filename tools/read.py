import os
from core import error_codes as ec
from core.sandbox import resolve_file
from core.tool_result import ToolResult, tool_exec_error


DEFINITION = {
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read the contents of a file. Returns lines with line numbers. "
                       "For large files, use offset and limit to read in chunks.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the file to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from, 1-indexed (default: 1)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: 200)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["full", "structure"],
                    "description": "Read mode: 'full' returns raw lines, 'structure' returns only structural lines",
                },
            },
            "required": ["path"],
        },
    },
}

MAX_LINE_CHARS = 500
STRUCTURE_PREFIXES = (
    "import ",
    "from ",
    "class ",
    "def ",
    "async def ",
    "@",
    "if ",
    "elif ",
    "else:",
    "for ",
    "while ",
    "try:",
    "except ",
    "finally:",
    "with ",
    "match ",
    "case ",
)


def _is_structure_line(line: str) -> bool:
    stripped = line.lstrip()
    return bool(stripped) and stripped.startswith(STRUCTURE_PREFIXES)


def execute(arguments):
    path = arguments["path"]
    raw_offset = arguments.get("offset", 1)
    raw_limit = arguments.get("limit", 200)
    mode = str(arguments.get("mode", "full")).strip().lower()
    try:
        offset = int(raw_offset)
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return ToolResult.error(
            ec.INVALID_ARGS,
            "offset and limit must be integers",
            path=path,
            offset=raw_offset,
            limit=raw_limit,
        )
    if offset <= 0:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "offset must be > 0",
            path=path,
            offset=offset,
        )
    if limit <= 0:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "limit must be > 0",
            path=path,
            limit=limit,
        )
    if mode not in {"full", "structure"}:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "mode must be one of: full, structure",
            path=path,
            mode=mode,
        )
    resolved_path, err = resolve_file(path)
    if err:
        return err
    if not os.access(resolved_path, os.R_OK):
        return ToolResult.error(
            ec.PERMISSION_DENIED,
            f"Permission denied: {path}",
            path=path,
        )

    # Binary file detection: inspect first 8KB for null byte
    with open(resolved_path, "rb") as f:
        if b"\x00" in f.read(8192):
            return ToolResult.error(
                ec.EXEC_FAILED,
                f"Binary file, cannot display: {path}",
                path=path,
            )

    try:
        with open(resolved_path, "r") as f:
            selected = []
            start = offset
            for line_no, line in enumerate(f, start=1):
                if line_no < start:
                    continue
                if mode == "structure" and not _is_structure_line(line):
                    continue
                selected.append((line_no, line))
                if len(selected) >= limit:
                    break
    except UnicodeDecodeError:
        return ToolResult.error(
            ec.EXEC_FAILED,
            f"File is not valid UTF-8 text: {path}",
            path=path,
        )
    except Exception as e:
        return tool_exec_error(ec.EXEC_FAILED, e, path=path)

    if not selected and mode == "full" and start == 1:
        return ToolResult.success(f"[File is empty: {path}]", path=path)
    if not selected:
        scope = "structure lines" if mode == "structure" else "lines"
        return ToolResult.success(
            f"[No {scope} found at or after offset={offset}]",
            path=path,
            mode=mode,
            offset=offset,
            limit=limit,
        )

    end = selected[-1][0]

    # Format output: line number + content, truncate long lines
    output_lines = []
    for i, line in selected:
        line = line.rstrip("\n")
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "... [truncated]"
        output_lines.append(f"{i:>6} | {line}")

    result = "\n".join(output_lines)
    first = selected[0][0]
    scope = "structure lines" if mode == "structure" else "lines"

    if len(selected) >= limit:
        result += f"\n\n[Showing {scope} {first}-{end}. Use offset={end+1} to continue reading.]"
    else:
        result += f"\n\n[Showing {scope} {first}-{end}]"

    return ToolResult.success(result, path=path, mode=mode, offset=offset, limit=limit)
