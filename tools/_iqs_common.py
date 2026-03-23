import requests

from core import error_codes as ec
from core.tool_result import ToolResult, tool_exec_error
from core.utils import get_cfg, load_config


_VALID_TIME_RANGES = {"OneDay", "OneWeek", "OneMonth", "OneYear", "NoLimit"}


def _invalid(message: str, **meta):
    return ToolResult.error(ec.INVALID_ARGS, message, **meta)


def _parse_int(value, name: str, **meta):
    try:
        return int(value), None
    except (TypeError, ValueError):
        payload = dict(meta)
        payload[name] = value
        return None, _invalid(f"{name} must be an integer", **payload)


def _load_iqs_key(**meta):
    api_key = get_cfg(load_config(), "search.iqs_api_key", "")
    if api_key:
        return api_key, None
    return None, ToolResult.error(
        ec.DEPENDENCY_MISSING,
        "iqs_api_key not configured in config.yaml",
        **meta,
    )


def _post(endpoint: str, headers: dict, body: dict, **meta):
    try:
        resp = requests.post(endpoint, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as e:
        return None, tool_exec_error(ec.NETWORK_FAILED, e, **meta)


def execute_iqs_web_search(arguments, endpoint: str):
    raw_query = arguments.get("query")
    query = str(raw_query or "").strip()
    if not query:
        return _invalid("query must be a non-empty string", query=raw_query)

    num_results, err = _parse_int(arguments.get("num_results", 5), "num_results", query=query)
    if err:
        return err
    if not 1 <= num_results <= 50:
        return _invalid("num_results must be between 1 and 50", query=query, num_results=num_results)

    raw_time_range = arguments.get("time_range", "NoLimit")
    time_range = str(raw_time_range or "").strip()
    if time_range not in _VALID_TIME_RANGES:
        return _invalid(
            "time_range must be one of: OneDay, OneWeek, OneMonth, OneYear, NoLimit",
            query=query,
            time_range=raw_time_range,
        )

    api_key, err = _load_iqs_key(query=query)
    if err:
        return err

    body = {
        "query": query,
        "engineType": "LiteAdvanced",
        "timeRange": time_range,
        "location": "southeast_asia",
        "contents": {"mainText": False, "markdownText": False, "summary": False},
        "advancedParams": {"numResults": str(num_results)},
    }
    data, err = _post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        body=body,
        query=query,
    )
    if err:
        return err

    items = data.get("pageItems") or []
    if not items:
        return ToolResult.success("No results found.", query=query, total=0)

    lines = [f"Found {len(items)} results:\n"]
    for i, item in enumerate(items, 1):
        title = item.get("title", "No title")
        url = item.get("link", "")
        snippet = item.get("snippet", "")
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."
        lines.extend([f"[{i}] {title}", f"    {url}", f"    {snippet}\n"])
    return ToolResult.success("\n".join(lines), query=query, total=len(items))


def execute_iqs_web_fetch(arguments, endpoint: str):
    raw_url = arguments.get("url")
    url = str(raw_url or "").strip()
    if not url:
        return _invalid("url must be a non-empty string", url=raw_url)
    if not url.startswith(("http://", "https://")):
        return _invalid("Invalid URL, must start with http:// or https://", url=url)

    max_chars, err = _parse_int(arguments.get("max_chars", 8000), "max_chars", url=url)
    if err:
        return err
    if max_chars < 1:
        return _invalid("max_chars must be >= 1", url=url, max_chars=max_chars)

    offset, err = _parse_int(arguments.get("offset", 0), "offset", url=url)
    if err:
        return err
    if offset < 0:
        return _invalid("offset must be >= 0", url=url, offset=offset)

    api_key, err = _load_iqs_key(url=url)
    if err:
        return err

    body = {
        "url": url,
        "location": "southeast_asia",
        "timeout": 60000,
        "maxAge": 1296000,
        "formats": ["markdown"],
        "readability": {"readabilityMode": "article", "excludeAllImages": True},
    }
    data, err = _post(
        endpoint,
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        body=body,
        url=url,
    )
    if err:
        return err

    page_data = data.get("data", {})
    title = page_data.get("metadata", {}).get("title", "")
    content = page_data.get("markdown", "") or page_data.get("text", "")
    if not content:
        return ToolResult.error(ec.EXEC_FAILED, "no content returned from page", url=url)

    total_chars = len(content)
    content = content[offset:]
    result = f"Title: {title}\n\n" if title else ""
    if len(content) > max_chars:
        next_offset = offset + max_chars
        result += content[:max_chars]
        result += f"\n\n[Showing chars {offset}-{next_offset} of {total_chars}. Use offset={next_offset} to continue reading.]"
    else:
        result += content
        if offset > 0:
            result += f"\n\n[Showing chars {offset}-{total_chars} of {total_chars}.]"
    return ToolResult.success(result, url=url, total_chars=total_chars, offset=offset, max_chars=max_chars)
