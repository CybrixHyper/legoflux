import os
from core import error_codes as ec
from core.sandbox import resolve_dir
from core.tool_result import ToolResult, limited_lines_output, tool_exec_error

DEFINITION = {
    "type": "function",
    "function": {
        "name": "list",
        "description": "List directory contents (one level). Returns entries sorted alphabetically, "
                       "with '/' suffix for directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return (default: 500)",
                },
            },
            "required": ["path"],
        },
    },
}


def execute(arguments):
    path = arguments["path"]
    limit = arguments.get("limit", 500)
    resolved_path, err = resolve_dir(path)
    if err:
        return err

    try:
        entries = os.listdir(resolved_path)
    except PermissionError:
        return ToolResult.error(
            ec.PERMISSION_DENIED,
            f"Permission denied: {path}",
            path=path,
        )
    except Exception as e:
        return tool_exec_error(ec.EXEC_FAILED, e, path=path)

    if not entries:
        return ToolResult.success("(empty directory)", path=path)

    # Format: append / for directories, then sort case-insensitively
    results = []
    for entry in entries:
        full_path = os.path.join(resolved_path, entry)
        if os.path.isdir(full_path):
            results.append(entry + "/")
        else:
            results.append(entry)

    results.sort(key=lambda x: x.lower())

    content, total, truncated = limited_lines_output(
        results,
        limit,
        "[{limit} entries shown out of {total}. Use limit={next_limit} for more.]",
    )
    if truncated:
        return ToolResult.success(content, path=path, total=total, limit=limit)
    return ToolResult.success(content, path=path, total=total)
