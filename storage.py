import os
from pathlib import Path

NOTES_DIR = Path(os.environ.get("NOTES_DIR", "notes"))


def _note_path(key: str) -> Path:
    return NOTES_DIR / f"{key}.md"


def list_notes() -> str:
    if not NOTES_DIR.exists():
        return "No notes yet."
    keys = [p.stem for p in sorted(NOTES_DIR.glob("*.md"))]
    return "\n".join(keys) if keys else "No notes yet."


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
