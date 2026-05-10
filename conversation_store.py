"""Persistent conversation store.

Saves full Claude Messages API conversation history (including tool_use
and tool_result blocks) to JSON files. One file per conversation, keyed
by Slack channel ID (DMs) or channel:thread_ts (threaded mentions).

Conversations are stored in CONVERSATIONS_DIR and gitignored.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CONVERSATIONS_DIR = Path(os.environ.get("CONVERSATIONS_DIR", "conversations"))


def _conversation_path(conversation_id: str) -> Path:
    """Return the file path for a conversation."""
    # Sanitize ID for filesystem (replace colons used in thread IDs)
    safe_id = conversation_id.replace(":", "_")
    return CONVERSATIONS_DIR / f"{safe_id}.json"


def load_conversation(conversation_id: str) -> list[dict]:
    """Load a conversation's message history. Returns empty list if none exists."""
    path = _conversation_path(conversation_id)
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("messages", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_conversation(conversation_id: str, messages: list[dict]) -> None:
    """Save a conversation's full message history to disk."""
    CONVERSATIONS_DIR.mkdir(exist_ok=True)
    path = _conversation_path(conversation_id)
    data = {
        "id": conversation_id,
        "messages": messages,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def clear_conversation(conversation_id: str) -> None:
    """Delete a conversation's history (fresh start)."""
    path = _conversation_path(conversation_id)
    if path.exists():
        path.unlink()
