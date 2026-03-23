import importlib
import os
import pkgutil

from core.error_codes import TOOL_UNKNOWN, INVALID_RESULT_TYPE
from core.tool_result import ToolResult

_REGISTRY = {}


def _available_tools():
    base_dir = os.path.dirname(__file__)
    names = []
    for mod in pkgutil.iter_modules([base_dir]):
        if mod.name.startswith("_"):
            continue
        if mod.name == "__init__":
            continue
        names.append(mod.name)
    return sorted(names)


def _ensure_loaded(names):
    """Auto-discover and load tool modules by name."""
    for name in names:
        if name not in _REGISTRY:
            module_name = f"tools.{name}"
            try:
                mod = importlib.import_module(module_name)
            except ModuleNotFoundError as e:
                # Only map "unknown tool module" to config error.
                # Re-raise dependency errors from inside tool modules.
                if getattr(e, "name", "") != module_name:
                    raise
                available = ", ".join(_available_tools())
                raise ValueError(
                    f"Invalid tool name '{name}'. Available tools: {available}"
                ) from None
            _REGISTRY[name] = mod


def get_tools(names):
    """Return a list of tool DEFINITION dicts for the given tool names."""
    _ensure_loaded(names)
    return [_REGISTRY[name].DEFINITION for name in names]


def process_tool_call(name, arguments):
    """Dispatch a tool call to the corresponding execute() function."""
    if name in _REGISTRY:
        result = _REGISTRY[name].execute(arguments)
        if isinstance(result, ToolResult):
            return result
        return ToolResult.error(
            INVALID_RESULT_TYPE,
            f"tool '{name}' returned invalid result type: {type(result).__name__}",
            content=f"Error: tool '{name}' returned invalid result type: {type(result).__name__}",
            tool=name,
            result_type=type(result).__name__,
        )
    return ToolResult.error(
        TOOL_UNKNOWN,
        f"unknown tool '{name}'",
        content=f"Error: unknown tool '{name}'",
        tool=name,
    )
