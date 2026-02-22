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
        "Save a fact about the user to long-term memory so it persists across conversations. "
        "Call this whenever you learn something that would change how you'd respond to this "
        "user in a future session.\n\n"
        "CALL for: name, location, job, relationships, dietary restrictions, preferences, "
        "recurring goals or habits, things they explicitly like or dislike.\n"
        "DON'T CALL for: one-time requests, questions they asked, or anything that only "
        "matters in this conversation.\n\n"
        "If a new fact contradicts something already in memory (e.g. they moved cities), "
        "save the new fact and note what it supersedes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": (
                    "A short declarative sentence. "
                    "Good: 'Lives in Austin, TX' or 'Vegetarian'. "
                    "Bad: 'The user told me they live in Austin' or 'User likes food'."
                ),
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
