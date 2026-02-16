import os
from pathlib import Path

MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", "memory"))


def _user_memory_path(user_id: str) -> Path:
    """Return the path to a user's memory file."""
    return MEMORY_DIR / f"{user_id}.md"


def read_memory(user_id: str) -> str:
    """Read all stored facts about a user. Returns empty string if none exist."""
    path = _user_memory_path(user_id)
    if not path.exists():
        return ""
    return path.read_text()


def save_memory(user_id: str, fact: str) -> str:
    """Append a fact about the user to their memory file."""
    MEMORY_DIR.mkdir(exist_ok=True)
    path = _user_memory_path(user_id)
    if not path.exists():
        path.write_text("# User Memory\n\n")
    with open(path, "a") as f:
        f.write(f"- {fact}\n")
    return f"Saved: {fact}"
