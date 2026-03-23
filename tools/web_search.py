import requests
from core import error_codes as ec
from core.tool_result import ToolResult, tool_exec_error
from core.utils import load_config, get_cfg

DEFINITION = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information. Returns titles, URLs, and snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results (1-50, default 5)",
                },
                "time_range": {
                    "type": "string",
                    "enum": ["OneDay", "OneWeek", "OneMonth", "OneYear", "NoLimit"],
                    "description": "Time filter (default: NoLimit)",
                },
            },
            "required": ["query"],
        },
    },
}

ENDPOINT = "https://cloud-iqs.aliyuncs.com/search/unified"
_VALID_TIME_RANGES = {"OneDay", "OneWeek", "OneMonth", "OneYear", "NoLimit"}


def execute(arguments):
    raw_query = arguments["query"]
    raw_num_results = arguments.get("num_results", 5)
    raw_time_range = arguments.get("time_range", "NoLimit")
    query = str(raw_query or "").strip()
    time_range = str(raw_time_range or "").strip()
    try:
        num_results = int(raw_num_results)
    except (TypeError, ValueError):
        return ToolResult.error(
            ec.INVALID_ARGS,
            "num_results must be an integer",
            query=raw_query,
            num_results=raw_num_results,
        )
    if not query:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "query must be a non-empty string",
            query=raw_query,
        )
    if num_results < 1 or num_results > 50:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "num_results must be between 1 and 50",
            query=query,
            num_results=num_results,
        )
    if time_range not in _VALID_TIME_RANGES:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "time_range must be one of: OneDay, OneWeek, OneMonth, OneYear, NoLimit",
            query=query,
            time_range=raw_time_range,
        )

    cfg = load_config()
    api_key = get_cfg(cfg, "search.iqs_api_key", "")
    if not api_key:
        return ToolResult.error(
            ec.DEPENDENCY_MISSING,
            "iqs_api_key not configured in config.yaml",
        )

    body = {
        "query": query,
        "engineType": "LiteAdvanced",
        "timeRange": time_range,
        "location": "southeast_asia",
        "contents": {
            "mainText": False,
            "markdownText": False,
            "summary": False,
        },
        "advancedParams": {
            "numResults": str(num_results),
        },
    }

    try:
        resp = requests.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return tool_exec_error(ec.NETWORK_FAILED, e, query=query)

    items = data.get("pageItems", [])
    if not items:
        return ToolResult.success("No results found.", query=query, total=0)

    lines = [f"Found {len(items)} results:\n"]
    for i, item in enumerate(items, 1):
        title = item.get("title", "No title")
        url = item.get("link", "")
        snippet = item.get("snippet", "")
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."
        lines.append(f"[{i}] {title}")
        lines.append(f"    {url}")
        lines.append(f"    {snippet}\n")

    return ToolResult.success(
        "\n".join(lines),
        query=query,
        total=len(items),
    )
