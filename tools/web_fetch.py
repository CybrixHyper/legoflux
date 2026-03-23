from tools._iqs_common import execute_iqs_web_fetch

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
    return execute_iqs_web_fetch(arguments, endpoint=ENDPOINT)
