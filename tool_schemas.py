"""OpenAI tool schema definitions.

Each dict describes a function tool for the OpenAI Responses API.
TOOLS is the master list passed as the `tools` argument on every API call.
To add a new tool: define a schema here, add it to TOOLS, then add a
dispatch branch in tools.py.
"""

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

DELETE_NOTE_TOOL = {
    "type": "function",
    "name": "delete_note",
    "description": (
        "Permanently delete a saved file by key. "
        "Use only when the user explicitly asks to delete or remove a note. "
        "If unsure of the exact filename, call list_notes first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The filename including extension. No path separators.",
            }
        },
        "required": ["key"],
        "additionalProperties": False,
    },
}

EDIT_NOTE_TOOL = {
    "type": "function",
    "name": "edit_note",
    "description": (
        "Replace an exact string in a file with new text. "
        "Use this for targeted edits: removing a list item, updating a value, renaming something. "
        "To delete text, pass an empty string for new_str. "
        "If old_str is not found, read the file first to verify the exact contents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The filename including extension. No path separators.",
            },
            "old_str": {
                "type": "string",
                "description": "The exact string to find and replace. Must match character-for-character.",
            },
            "new_str": {
                "type": "string",
                "description": "The string to replace it with. Pass empty string to delete.",
            },
        },
        "required": ["key", "old_str", "new_str"],
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
    DELETE_NOTE_TOOL,
    EDIT_NOTE_TOOL,
]
