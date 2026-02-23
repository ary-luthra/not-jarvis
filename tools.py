"""OpenAI tool dispatch logic.

To add a new tool: define its schema in tool_schemas.py, add it to TOOLS
there, then add a dispatch branch in `dispatch_function_call` below.
"""

import json

from config import logger
from memory import save_memory
from file_storage import list_notes, read_note, write_note, append_to_note, edit_note, delete_note
from tool_schemas import TOOLS  # noqa: F401  re-exported for bot.py

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch_function_call(name: str, arguments: str, username: str) -> str:
    """Execute a function tool by name and return the result string."""
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse arguments for %s: %s", name, e)
        return f"Error: could not parse arguments — {e}"

    try:
        if name == "save_memory":
            result = save_memory(username, args["fact"])
            logger.info("Memory saved for %s: %s", username, args["fact"])
            return result
        if name == "list_notes":
            return list_notes()
        if name == "read_note":
            return read_note(args["key"])
        if name == "write_note":
            return write_note(args["key"], args["content"])
        if name == "append_to_note":
            return append_to_note(args["key"], args["content"])
        if name == "delete_note":
            return delete_note(args["key"])
        if name == "edit_note":
            return edit_note(args["key"], args["old_str"], args["new_str"])
    except KeyError as e:
        logger.error("Missing required argument for %s: %s", name, e)
        return f"Error: missing required argument {e}"
    except ValueError as e:
        logger.error("Invalid argument for %s: %s", name, e)
        return f"Error: {e}"
    except OSError as e:
        logger.error("File system error in %s: %s", name, e)
        return f"Error: file system error — {e}"

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
