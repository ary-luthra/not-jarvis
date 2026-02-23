"""OpenAI tool definitions and dispatch logic.

Add new function tools here. Each tool needs:
1. A schema dict describing it for the OpenAI API.
2. A handler entry in `dispatch_function_call` that executes it.
"""

import json

from config import logger
from memory import save_memory
from storage import list_notes, read_note, write_note, append_to_note

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

LIST_NOTES_TOOL = {
    "type": "function",
    "name": "list_notes",
    "description": (
        "List all saved notes and files by name (including their extensions). "
        "Call this first when the user asks what's stored, or before reading a note "
        "if you're not sure whether it exists."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}

READ_NOTE_TOOL = {
    "type": "function",
    "name": "read_note",
    "description": (
        "Read the full contents of a saved file by key (filename including extension). "
        "Use this when the user asks to see a list or recall something stored."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The filename including extension (e.g. 'grocery_list.md', 'reminders.json'). No path separators.",
            }
        },
        "required": ["key"],
        "additionalProperties": False,
    },
}

WRITE_NOTE_TOOL = {
    "type": "function",
    "name": "write_note",
    "description": (
        "Write or completely overwrite a file. "
        "Choose the format and extension that best fits the data: "
        ".md for prose or bullet lists, .json for structured records, .jsonl for append-heavy logs. "
        "For adding to an existing file, use append_to_note instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The filename including extension. No path separators.",
            },
            "content": {
                "type": "string",
                "description": "The full content to write.",
            },
        },
        "required": ["key", "content"],
        "additionalProperties": False,
    },
}

APPEND_TO_NOTE_TOOL = {
    "type": "function",
    "name": "append_to_note",
    "description": (
        "Append content to the end of a file. "
        "Use this when adding to an existing list or log (e.g. 'add milk to grocery list', new JSONL record). "
        "Creates the file if it doesn't exist yet."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The filename including extension. No path separators.",
            },
            "content": {
                "type": "string",
                "description": "The content to append.",
            },
        },
        "required": ["key", "content"],
        "additionalProperties": False,
    },
}

# Master list passed to the OpenAI Responses API.
# Hosted tools (like web_search_preview) go here alongside function tools.
TOOLS = [
    {"type": "web_search_preview"},
    SAVE_MEMORY_TOOL,
    LIST_NOTES_TOOL,
    READ_NOTE_TOOL,
    WRITE_NOTE_TOOL,
    APPEND_TO_NOTE_TOOL,
]

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch_function_call(name: str, arguments: str, username: str) -> str:
    """Execute a function tool by name and return the result string."""
    args = json.loads(arguments) if arguments else {}

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
