import os
import difflib
from core import error_codes as ec
from core.sandbox import resolve_file
from core.tool_result import ToolResult, tool_exec_error
from core.utils import atomic_write_text

DEFINITION = {
    "type": "function",
    "function": {
        "name": "edit",
        "description": "Edit an existing file by replacing old_str with new_str. "
                       "old_str must appear exactly once in the file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the file to edit",
                },
                "old_str": {
                    "type": "string",
                    "description": "The exact string to find and replace",
                },
                "new_str": {
                    "type": "string",
                    "description": "The replacement string",
                },
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
}


def execute(arguments):
    path = arguments["path"]
    old_str = arguments["old_str"]
    new_str = arguments["new_str"]
    resolved_path, err = resolve_file(path)
    if err:
        return err
    if not os.access(resolved_path, os.R_OK | os.W_OK):
        return ToolResult.error(
            ec.PERMISSION_DENIED,
            f"Permission denied: {path}",
            path=path,
        )

    if old_str == new_str:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "old_str and new_str are identical, no changes needed",
            path=path,
        )

    try:
        with open(resolved_path, "r") as f:
            content = f.read()
    except Exception as e:
        return tool_exec_error(ec.EXEC_FAILED, e, path=path)

    count = content.count(old_str)
    if count == 0:
        return ToolResult.error(
            ec.NOT_FOUND,
            f"old_str not found in {path}",
            path=path,
        )
    if count > 1:
        return ToolResult.error(
            ec.INVALID_ARGS,
            f"old_str found {count} times in {path}, must be unique",
            path=path,
            count=count,
        )

    new_content = content.replace(old_str, new_str, 1)
    atomic_write_text(resolved_path, new_content)

    # Generate unified diff output
    old_lines = content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=path, tofile=path, lineterm="")
    diff_str = "".join(diff).strip()

    return ToolResult.success(
        f"Edited file: {path}\n\n{diff_str}",
        path=path,
    )
