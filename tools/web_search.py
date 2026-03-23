from tools._iqs_common import execute_iqs_web_search

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
    return execute_iqs_web_search(arguments, endpoint=ENDPOINT)
