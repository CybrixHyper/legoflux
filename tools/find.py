import os
import glob as globlib
from core import error_codes as ec
from core.sandbox import resolve_dir
from core.tool_result import ToolResult, limited_lines_output, tool_exec_error

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".devenv"}

DEFINITION = {
    "type": "function",
    "function": {
        "name": "find",
        "description": "Search for files by glob pattern. Returns matching file paths relative to the search directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files, e.g. '*.py', '**/*.json', 'test_*'",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: current directory)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 200)",
                },
            },
            "required": ["pattern"],
        },
    },
}


def execute(arguments):
    pattern = arguments["pattern"]
    path = arguments.get("path", ".")
    limit = arguments.get("limit", 200)
    resolved_path, err = resolve_dir(path)
    if err:
        return err

    # If pattern does not include **, auto-prefix with **/ for recursive search
    if "**" not in pattern and os.sep not in pattern and "/" not in pattern:
        search_pattern = os.path.join(resolved_path, "**", pattern)
    else:
        search_pattern = os.path.join(resolved_path, pattern)

    try:
        matches = globlib.glob(search_pattern, recursive=True)
    except Exception as e:
        return tool_exec_error(ec.EXEC_FAILED, e, path=path, pattern=pattern)

    # Skip entries under SKIP_DIRS and keep files only
    filtered = []
    for match in matches:
        if not os.path.isfile(match):
            continue
        parts = match.replace("\\", "/").split("/")
        if any(part in SKIP_DIRS for part in parts):
            continue
        filtered.append(match)

    if not filtered:
        return ToolResult.success(
            "No files found matching pattern.",
            path=path,
            pattern=pattern,
        )

    # Convert to relative paths and sort
    results = [os.path.relpath(m, resolved_path) for m in filtered]
    results.sort(key=lambda x: x.lower())

    content, total, truncated = limited_lines_output(
        results,
        limit,
        "[{limit} results shown out of {total}. Use limit={next_limit} for more.]",
    )
    if truncated:
        return ToolResult.success(content, path=path, pattern=pattern, total=total, limit=limit)
    return ToolResult.success(content, path=path, pattern=pattern, total=total)
