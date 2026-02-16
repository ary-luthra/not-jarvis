"""OpenAI tool definitions and dispatch logic.

Add new function tools here. Each tool needs:
1. A schema dict describing it for the OpenAI API.
2. A handler entry in `dispatch_function_call` that executes it.
"""

import json

from config import logger
from memory import save_memory

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

SAVE_MEMORY_TOOL = {
    "type": "function",
    "name": "save_memory",
    "description": (
        "Save an important fact or preference about the user to long-term memory. "
        "Use this when the user shares personal information, preferences, or any "
        "detail worth remembering across conversations. Examples: where they live, "
        "their job, their name, food preferences, etc."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "A concise fact about the user to remember",
            }
        },
        "required": ["fact"],
        "additionalProperties": False,
    },
}

# Master list passed to the OpenAI Responses API.
# Hosted tools (like web_search_preview) go here alongside function tools.
TOOLS = [
    {"type": "web_search_preview"},
    SAVE_MEMORY_TOOL,
]

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch_function_call(name: str, arguments: str, username: str) -> str:
    """Execute a function tool by name and return the result string."""
    if name == "save_memory":
        args = json.loads(arguments)
        result = save_memory(username, args["fact"])
        logger.info("Memory saved for %s: %s", username, args["fact"])
        return result
    return f"Unknown function: {name}"


def handle_function_calls(response, username: str) -> list[dict]:
    """Process function-call items in a response and return tool outputs."""
    tool_outputs = []
    for item in response.output:
        if item.type != "function_call":
            continue
        result = dispatch_function_call(item.name, item.arguments, username)
        tool_outputs.append({
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": result,
        })
    return tool_outputs
