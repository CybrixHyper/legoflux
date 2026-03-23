import requests
from core import error_codes as ec
from core.tool_result import ToolResult, tool_exec_error
from core.utils import load_config, get_cfg

DEFINITION = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "Fetch a web page and return its content as markdown. Use this after web_search to read a specific page.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch (must start with http:// or https://)",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default 8000)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Character offset to start reading from (default: 0)",
                },
            },
            "required": ["url"],
        },
    },
}

ENDPOINT = "https://cloud-iqs.aliyuncs.com/readpage/basic"


def execute(arguments):
    raw_url = arguments["url"]
    raw_max_chars = arguments.get("max_chars", 8000)
    raw_offset = arguments.get("offset", 0)
    url = str(raw_url or "").strip()
    try:
        max_chars = int(raw_max_chars)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        return ToolResult.error(
            ec.INVALID_ARGS,
            "max_chars and offset must be integers",
            url=raw_url,
            max_chars=raw_max_chars,
            offset=raw_offset,
        )
    if max_chars <= 0:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "max_chars must be > 0",
            url=url,
            max_chars=max_chars,
        )
    if offset < 0:
        return ToolResult.error(
            ec.INVALID_ARGS,
            "offset must be >= 0",
            url=url,
            offset=offset,
        )

    if not url.startswith(("http://", "https://")):
        return ToolResult.error(
            ec.INVALID_ARGS,
            "Invalid URL, must start with http:// or https://",
            url=url,
        )

    cfg = load_config()
    api_key = get_cfg(cfg, "search.iqs_api_key", "")
    if not api_key:
        return ToolResult.error(
            ec.DEPENDENCY_MISSING,
            "iqs_api_key not configured in config.yaml",
            url=url,
        )

    body = {
        "url": url,
        "location": "southeast_asia",
        "timeout": 60000,
        "maxAge": 1296000,
        "formats": ["markdown"],
        "readability": {
            "readabilityMode": "article",
            "excludeAllImages": True,
        },
    }

    try:
        resp = requests.post(
            ENDPOINT,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return tool_exec_error(ec.NETWORK_FAILED, e, url=url)

    page_data = data.get("data", {})
    title = page_data.get("metadata", {}).get("title", "")
    content = page_data.get("markdown", "") or page_data.get("text", "")

    if not content:
        return ToolResult.error(
            ec.EXEC_FAILED,
            "no content returned from page",
            url=url,
        )

    total_chars = len(content)
    content = content[offset:]

    result = ""
    if title:
        result = f"Title: {title}\n\n"

    if len(content) > max_chars:
        result += content[:max_chars]
        next_offset = offset + max_chars
        result += f"\n\n[Showing chars {offset}-{next_offset} of {total_chars}. Use offset={next_offset} to continue reading.]"
    else:
        result += content
        if offset > 0:
            result += f"\n\n[Showing chars {offset}-{total_chars} of {total_chars}.]"

    return ToolResult.success(
        result,
        url=url,
        total_chars=total_chars,
        offset=offset,
        max_chars=max_chars,
    )
