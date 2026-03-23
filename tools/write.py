import os
from core import error_codes as ec
from core.sandbox import resolve_path
from core.tool_result import ToolResult, tool_exec_error
from core.utils import atomic_write_text

DEFINITION = {
    "type": "function",
    "function": {
        "name": "write",
        "description": "Create a new file or overwrite an existing file. "
                       "Automatically creates parent directories if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    },
}


def execute(arguments):
    path = arguments["path"]
    content = arguments["content"]
    resolved_path, err = resolve_path(path)
    if err:
        return err

    try:
        created = not os.path.exists(resolved_path)
        atomic_write_text(resolved_path, content)

        if created:
            return ToolResult.success(f"Created new file: {path}", path=path, created=True)
        return ToolResult.success(
            f"Wrote {len(content)} chars to: {path}",
            path=path,
            created=False,
            chars=len(content),
        )
    except PermissionError:
        return ToolResult.error(
            ec.PERMISSION_DENIED,
            f"Permission denied: {path}",
            path=path,
        )
    except Exception as e:
        return tool_exec_error(ec.EXEC_FAILED, e, path=path)
