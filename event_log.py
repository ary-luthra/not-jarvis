"""Shared event bus for observability.

Both the orchestrator (bot.py) and session manager write events here.
The TUI dashboard and JSON file logger read from it.

Events are stored in a bounded deque (in-memory, lost on restart)
and optionally written to a JSONL file for history.
"""

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))
MAX_EVENTS = 2000  # keep last N events in memory


@dataclass
class Event:
    """A single observable event."""
    timestamp: str
    category: str       # "orchestrator" | "session" | "system"
    event_type: str     # e.g. "agent_turn", "tool_call", "session_dispatch", "user_message"
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class EventLog:
    """Thread-safe event bus with in-memory buffer and optional disk logging."""

    def __init__(self, enable_file_log: bool = True):
        self._events: deque[Event] = deque(maxlen=MAX_EVENTS)
        self._lock = threading.Lock()
        self._listeners: list[Callable[[Event], None]] = []
        self._file_log = None

        if enable_file_log:
            LOG_DIR.mkdir(exist_ok=True)
            log_path = LOG_DIR / f"events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
            self._file_log = open(log_path, "a")

    def emit(self, category: str, event_type: str, **data: Any) -> Event:
        """Create and store an event, notify listeners, optionally write to disk."""
        event = Event(
            timestamp=datetime.now(timezone.utc).isoformat(),
            category=category,
            event_type=event_type,
            data=data,
        )

        with self._lock:
            self._events.append(event)

            if self._file_log:
                self._file_log.write(event.to_json() + "\n")
                self._file_log.flush()

        # Notify listeners outside the lock
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass

        return event

    def subscribe(self, listener: Callable[[Event], None]):
        """Register a callback that fires on every new event."""
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[Event], None]):
        """Remove a listener."""
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def get_events(
        self,
        category: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Read recent events, optionally filtered."""
        with self._lock:
            events = list(self._events)

        if category:
            events = [e for e in events if e.category == category]
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        return events[-limit:]

    def get_session_events(self, session_id: str, limit: int = 50) -> list[Event]:
        """Get events for a specific Claude Code session."""
        with self._lock:
            events = list(self._events)
        return [
            e for e in events
            if e.data.get("session_id") == session_id
        ][-limit:]

    def close(self):
        if self._file_log:
            self._file_log.close()


# Module-level singleton
event_log = EventLog()
