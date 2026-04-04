"""OpenAI tool dispatch logic.

To add a new tool: define its schema in tool_schemas.py, add it to TOOLS
there, then add a dispatch branch in `dispatch_function_call` below.
"""

import json

from config import logger
from memory import save_memory
from session_manager import session_manager
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
        if name == "dispatch_computer_task":
            session = session_manager.dispatch(
                task=args["task"],
                use_browser=args.get("use_browser", False),
                isolate=args.get("isolate", False),
            )
            logger.info("Dispatched session %s for: %s", session.internal_id, args["task"][:80])
            return json.dumps({
                "session_id": session.internal_id,
                "status": "dispatched",
                "message": f"Task dispatched as {session.internal_id}. Use read_task_output to check progress.",
            })
        if name == "list_computer_tasks":
            sessions = session_manager.list_sessions()
            if not sessions:
                return "No computer tasks have been dispatched yet."
            return json.dumps(sessions, indent=2)
        if name == "read_task_output":
            return session_manager.read_output(args["session_id"])
        if name == "send_followup_to_task":
            return session_manager.send_followup(args["session_id"], args["message"])
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
