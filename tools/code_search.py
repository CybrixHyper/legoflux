import os
import subprocess
from core import error_codes as ec
from core.sandbox import resolve_dir
from core.tool_result import ToolResult, limited_lines_output, tool_exec_error

# Minimal env: rg only needs PATH to locate itself
_SEARCH_ENV = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "HOME")}

DEFINITION = {
    "type": "function",
    "function": {
        "name": "code_search",
        "description": "Search for a pattern in code files using ripgrep. Returns matching lines with file paths and line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in (default: current directory)",
                },
                "glob": {
                    "type": "string",
                    "description": "Filter files by glob pattern, e.g. '*.py', '*.ts'",
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default: 50)",
                },
            },
            "required": ["pattern"],
        },
    },
}


def execute(arguments):
    pattern = arguments["pattern"]
    path = arguments.get("path", ".")
    file_glob = arguments.get("glob")
    ignore_case = arguments.get("ignore_case", False)
    limit = arguments.get("limit", 50)
    resolved_path, err = resolve_dir(path)
    if err:
        return err

    try:
        cmd = ["rg", "--line-number", "--no-heading", "--color=never"]
        if ignore_case:
            cmd.append("--ignore-case")
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.extend([pattern, resolved_path])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            env=_SEARCH_ENV,
        )
        if result.returncode == 1:
            return ToolResult.success("No matches found.", path=path, pattern=pattern)
        if result.returncode > 1:
            return ToolResult.error(
                ec.EXEC_FAILED,
                result.stderr.strip() or f"rg returned code {result.returncode}",
                path=path,
                pattern=pattern,
                exit_code=int(result.returncode),
            )

        lines = result.stdout.splitlines()
        content, total, truncated = limited_lines_output(
            lines,
            limit,
            "[{limit} matches shown out of {total}. Use limit={next_limit} for more, or refine pattern.]",
        )
        if truncated:
            return ToolResult.success(content, path=path, pattern=pattern, total=total, limit=limit)
        return ToolResult.success(content if content else "No matches found.", path=path, pattern=pattern, total=total)
    except FileNotFoundError:
        return ToolResult.error(
            ec.DEPENDENCY_MISSING,
            "ripgrep (rg) is not installed. Install it with: brew install ripgrep",
            path=path,
        )
    except subprocess.TimeoutExpired:
        return ToolResult.error(
            ec.TIMEOUT,
            "search timed out after 15 seconds",
            path=path,
            pattern=pattern,
        )
    except Exception as e:
        return tool_exec_error(ec.EXEC_FAILED, e, path=path, pattern=pattern)
