"""Manages Claude Code sessions as background subprocesses.

Provides a Dispatch-style orchestrator: spawn tasks, track them,
read their output passively, and send follow-ups when needed.

Sandbox enforcement uses Claude Code's native sandbox (macOS Seatbelt /
Linux bubblewrap) via --settings, which blocks file writes at the OS level.
"""

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import logger
from event_log import event_log

CLAUDE_CODE_PATH = os.environ.get("CLAUDE_CODE_PATH", "claude")
MAX_CONCURRENT_SESSIONS = int(os.environ.get("MAX_CONCURRENT_SESSIONS", "3"))
DEFAULT_MAX_TURNS = int(os.environ.get("DEFAULT_MAX_TURNS", "10"))
DEFAULT_ALLOWED_TOOLS = os.environ.get(
    "DEFAULT_ALLOWED_TOOLS", "Bash,Read,Edit,Write,Glob,Grep"
)
SANDBOX_DIR = os.path.abspath(os.environ.get("SANDBOX_DIR", "sandbox"))

# Settings JSON for Claude Code's native sandbox.
# sandbox.filesystem rules are enforced at the OS level (Seatbelt/bubblewrap),
# not prompt-level. permission.deny rules block Claude's built-in file tools.
_SANDBOX_SETTINGS = json.dumps({
    "permissions": {
        "deny": [
            "Edit(///**)",
            "Write(///**)",
        ],
        "allow": [
            f"Edit({SANDBOX_DIR}/**)",
            f"Write({SANDBOX_DIR}/**)",
            "Read",
            "Bash",
            "Glob",
            "Grep",
        ],
    },
    "sandbox": {
        "enabled": True,
        "filesystem": {
            "allowWrite": [SANDBOX_DIR],
            "denyWrite": ["~/", "//"],
            "allowRead": [".", "~/"],
        },
    },
})


def _ensure_sandbox_dir():
    """Create the sandbox directory and a CLAUDE.md with rules."""
    os.makedirs(SANDBOX_DIR, exist_ok=True)
    claude_md = os.path.join(SANDBOX_DIR, "CLAUDE.md")
    if not os.path.exists(claude_md):
        with open(claude_md, "w") as f:
            f.write(
                "# Sandbox\n\n"
                "All file operations are restricted to this directory.\n"
                "Use relative paths. Do not attempt to write outside this folder.\n"
            )


@dataclass
class Session:
    """A single Claude Code subprocess session."""

    internal_id: str  # Our tracking ID (assigned before claude starts)
    task: str
    process: subprocess.Popen
    use_browser: bool = False
    worktree: str | None = None
    session_id: str | None = None  # Claude Code's UUID, parsed from output
    status: str = "running"  # running | done | failed
    result: str | None = None
    cost: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _output_lines: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self._reader_thread = threading.Thread(
            target=self._read_stdout, daemon=True
        )
        self._reader_thread.start()

    def _read_stdout(self):
        """Continuously read stdout lines from the subprocess."""
        for raw_line in self.process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            with self._lock:
                self._output_lines.append(line)
            try:
                data = json.loads(line)
                msg_type = data.get("type")

                if msg_type == "system" and data.get("subtype") == "init":
                    self.session_id = data.get("session_id")

                elif msg_type == "assistant":
                    # Log tool calls and text from the session
                    for block in data.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            event_log.emit("session", "tool_call",
                                           session_id=self.internal_id,
                                           tool=block.get("name", "?"),
                                           input_preview=json.dumps(block.get("input", {}))[:200])
                        elif block.get("type") == "text" and block.get("text"):
                            event_log.emit("session", "assistant_text",
                                           session_id=self.internal_id,
                                           text=block["text"][:300])

                elif msg_type == "result":
                    self.result = data.get("result")
                    self.cost = data.get("total_cost_usd", 0.0)
                    self.status = "done" if not data.get("is_error") else "failed"
                    event_log.emit("session", "session_end",
                                   session_id=self.internal_id,
                                   status=self.status,
                                   cost=self.cost,
                                   result_preview=(self.result or "")[:300],
                                   duration_s=round(self.age_seconds()))

            except json.JSONDecodeError:
                pass

    def poll(self):
        """Update status by checking if the subprocess is still alive."""
        if self.status == "running" and self.process.poll() is not None:
            self._reader_thread.join(timeout=2)
            if self.status == "running":
                self.status = "failed" if self.process.returncode != 0 else "done"

    def get_output_lines(self) -> list[str]:
        with self._lock:
            return list(self._output_lines)

    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()


class SessionManager:
    """Tracks and manages Claude Code subprocess sessions."""

    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"task-{self._counter}"

    def dispatch(
        self,
        task: str,
        use_browser: bool = False,
        isolate: bool = False,
    ) -> Session:
        """Spawn a new Claude Code session as a background subprocess."""
        running = [s for s in self.sessions.values() if s.status == "running"]
        if len(running) >= MAX_CONCURRENT_SESSIONS:
            raise RuntimeError(
                f"Already running {len(running)} sessions "
                f"(max {MAX_CONCURRENT_SESSIONS}). "
                "Wait for one to finish or check existing tasks."
            )

        _ensure_sandbox_dir()

        sandboxed_task = (
            f"You are in a sandboxed workspace at {SANDBOX_DIR}. "
            f"All file operations must stay in this directory. "
            f"Use relative paths.\n\n"
            f"Task: {task}"
        )

        cmd = [
            CLAUDE_CODE_PATH,
            "-p", sandboxed_task,
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", str(DEFAULT_MAX_TURNS),
            "--allowedTools", DEFAULT_ALLOWED_TOOLS,
            "--settings", _SANDBOX_SETTINGS,
        ]
        if use_browser:
            cmd.append("--chrome")
        if isolate:
            cmd.extend(["--worktree", f"task-{self._counter + 1}"])

        internal_id = self._next_id()
        logger.info("Dispatching session %s: %s", internal_id, task[:100])

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=SANDBOX_DIR,
        )

        session = Session(
            internal_id=internal_id,
            task=task,
            process=process,
            use_browser=use_browser,
            worktree=f"task-{self._counter}" if isolate else None,
        )
        self.sessions[internal_id] = session

        event_log.emit("session", "session_dispatch",
                       session_id=internal_id,
                       task=task[:200],
                       use_browser=use_browser,
                       isolate=isolate)

        time.sleep(0.5)
        return session

    def list_sessions(self) -> list[dict]:
        """Return all tracked sessions with their current status."""
        result = []
        for sid, session in self.sessions.items():
            session.poll()
            result.append({
                "id": sid,
                "session_id": session.session_id,
                "task": session.task[:120],
                "status": session.status,
                "age_seconds": round(session.age_seconds()),
                "use_browser": session.use_browser,
                "cost": session.cost,
            })
        return result

    def read_output(self, internal_id: str) -> str:
        """Read the stream-json output captured so far. Passive, no interaction."""
        session = self.sessions.get(internal_id)
        if not session:
            return f"No session found with id '{internal_id}'."

        session.poll()
        lines = session.get_output_lines()
        if not lines:
            return f"Session {internal_id} ({session.status}): no output yet."

        summary_parts = [f"Session {internal_id} — status: {session.status}"]
        if session.status == "done" and session.result:
            summary_parts.append(f"\n**Final result:**\n{session.result}")
            return "\n".join(summary_parts)

        for line in lines:
            try:
                data = json.loads(line)
                msg_type = data.get("type")

                if msg_type == "assistant":
                    message = data.get("message", {})
                    for block in message.get("content", []):
                        if block.get("type") == "text" and block.get("text"):
                            summary_parts.append(f"Assistant: {block['text'][:500]}")
                        elif block.get("type") == "tool_use":
                            summary_parts.append(
                                f"Tool call: {block.get('name', '?')} "
                                f"({json.dumps(block.get('input', {}))[:200]})"
                            )

                elif msg_type == "tool_result":
                    content = data.get("content", "")
                    if isinstance(content, str) and content:
                        summary_parts.append(f"Tool result: {content[:300]}")

            except json.JSONDecodeError:
                continue

        if len(summary_parts) == 1:
            summary_parts.append("(processing, no content captured yet)")

        return "\n".join(summary_parts)

    def send_followup(self, internal_id: str, message: str) -> str:
        """Resume a session with a follow-up prompt. Spawns a new subprocess."""
        session = self.sessions.get(internal_id)
        if not session:
            return f"No session found with id '{internal_id}'."
        if not session.session_id:
            return f"Session {internal_id} hasn't produced a session_id yet. Try again shortly."
        if session.status == "running":
            return f"Session {internal_id} is still running. Wait for it to finish or read its output."

        cmd = [
            CLAUDE_CODE_PATH,
            "-p", message,
            "--resume", session.session_id,
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", str(DEFAULT_MAX_TURNS),
            "--allowedTools", DEFAULT_ALLOWED_TOOLS,
            "--settings", _SANDBOX_SETTINGS,
        ]
        if session.use_browser:
            cmd.append("--chrome")

        logger.info("Sending follow-up to session %s: %s", internal_id, message[:100])
        event_log.emit("session", "session_followup",
                       session_id=internal_id, message=message[:200])

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=SANDBOX_DIR,
        )

        session.process = process
        session.status = "running"
        session.result = None
        session._output_lines = []
        session._reader_thread = threading.Thread(
            target=session._read_stdout, daemon=True
        )
        session._reader_thread.start()
        time.sleep(0.5)

        return f"Follow-up sent to session {internal_id}. Check back for results."

    def cleanup(self, internal_id: str) -> str:
        """Kill a running session."""
        session = self.sessions.get(internal_id)
        if not session:
            return f"No session found with id '{internal_id}'."
        if session.status == "running":
            session.process.terminate()
            session.status = "failed"
        del self.sessions[internal_id]
        return f"Session {internal_id} cleaned up."


# Module-level singleton
session_manager = SessionManager()
