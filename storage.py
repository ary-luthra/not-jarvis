import os
from pathlib import Path

NOTES_DIR = Path(os.environ.get("NOTES_DIR", "notes"))


def _note_path(key: str) -> Path:
    if "/" in key or "\\" in key or ".." in key:
        raise ValueError(f"Invalid key: {key!r}")
    return NOTES_DIR / key


def list_notes() -> str:
    if not NOTES_DIR.exists():
        return "No notes yet."
    files = sorted(p.name for p in NOTES_DIR.iterdir() if p.is_file())
    return "\n".join(files) if files else "No notes yet."


def read_note(key: str) -> str:
    path = _note_path(key)
    if not path.exists():
        return f"No note found for '{key}'."
    return path.read_text()


def write_note(key: str, content: str) -> str:
    NOTES_DIR.mkdir(exist_ok=True)
    _note_path(key).write_text(content)
    return f"Saved '{key}'."


def append_to_note(key: str, content: str) -> str:
    NOTES_DIR.mkdir(exist_ok=True)
    path = _note_path(key)
    with open(path, "a") as f:
        f.write(f"\n{content}")
    return f"Appended to '{key}'."


def edit_note(key: str, old_str: str, new_str: str) -> str:
    path = _note_path(key)
    if not path.exists():
        return f"No note found for '{key}'."
    content = path.read_text()
    count = content.count(old_str)
    if count == 0:
        return f"String not found in '{key}'. Read the file first to check exact contents."
    if count > 1:
        return f"Found {count} matches in '{key}'. Provide more surrounding context to make old_str unique."
    path.write_text(content.replace(old_str, new_str, 1))
    return f"Edited '{key}'."
