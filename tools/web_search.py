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


def execute(arguments):
    query = arguments["query"]
    num_results = arguments.get("num_results", 5)
    time_range = arguments.get("time_range", "NoLimit")

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
