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

# ---------------------------------------------------------------------------
# Computer task dispatch (Claude Code sessions)
# ---------------------------------------------------------------------------

DISPATCH_COMPUTER_TASK_TOOL = {
    "type": "function",
    "name": "dispatch_computer_task",
    "description": (
        "Dispatch a task to a Claude Code session running on this computer. "
        "This runs in the background — acknowledge the dispatch to the user and move on. "
        "Do NOT poll or wait for results. Only check on it later if the user asks.\n\n"
        "Use this for tasks that require interacting with the computer: "
        "running shell commands, editing files, or browser actions.\n\n"
        "For multiple independent tasks, call this multiple times — they run in parallel.\n"
        "Set use_browser=true ONLY for tasks that require real browser interaction "
        "(logging into websites, clicking buttons, filling forms, taking screenshots). "
        "Do NOT use browser for simple information lookups — Claude Code has web search built in.\n"
        "Set isolate=true for file-editing tasks that might conflict with each other."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "A clear description of what to do on the computer.",
            },
            "use_browser": {
                "type": "boolean",
                "description": (
                    "Whether the task needs a real Chrome browser. "
                    "Use for: logging into sites, clicking UI, filling forms, screenshotting pages. "
                    "Do NOT use for simple lookups — use web_search_preview instead."
                ),
                "default": False,
            },
            "isolate": {
                "type": "boolean",
                "description": "Whether to use a git worktree for file isolation.",
                "default": False,
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    },
}

LIST_COMPUTER_TASKS_TOOL = {
    "type": "function",
    "name": "list_computer_tasks",
    "description": (
        "List all Claude Code sessions (running, completed, or failed) "
        "with their status, age, and task description. "
        "Call this when the user asks about the status of their tasks, "
        "or before dispatching to see what's already running."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}

READ_TASK_OUTPUT_TOOL = {
    "type": "function",
    "name": "read_task_output",
    "description": (
        "Read the output of a Claude Code session so far. "
        "This is a FREE passive peek — it reads captured stdout without "
        "interacting with the session or costing any tokens.\n\n"
        "Use this to check on progress, see what tool calls were made, "
        "or get the final result of a completed session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session ID returned by dispatch_computer_task (e.g. 'task-1').",
            },
        },
        "required": ["session_id"],
        "additionalProperties": False,
    },
}

SEND_FOLLOWUP_TO_TASK_TOOL = {
    "type": "function",
    "name": "send_followup_to_task",
    "description": (
        "Send a follow-up message to a COMPLETED Claude Code session, "
        "resuming it with new instructions. This starts a new turn and costs tokens.\n\n"
        "Use only when you need to redirect, add instructions, or ask for more work. "
        "To just peek at output, use read_task_output instead.\n\n"
        "Cannot be used on sessions that are still running."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session ID (e.g. 'task-1').",
            },
            "message": {
                "type": "string",
                "description": "The follow-up instruction to send.",
            },
        },
        "required": ["session_id", "message"],
        "additionalProperties": False,
    },
}

# Master list passed to the OpenAI Responses API.
# Hosted tools (like web_search_preview) go here alongside function tools.
TOOLS = [
    {"type": "web_search_preview"},
    SAVE_MEMORY_TOOL,
    DISPATCH_COMPUTER_TASK_TOOL,
    LIST_COMPUTER_TASKS_TOOL,
    READ_TASK_OUTPUT_TOOL,
    SEND_FOLLOWUP_TO_TASK_TOOL,
]
