"""Event types passed between components via buses."""

from dataclasses import dataclass, field
from typing import Literal
import uuid


@dataclass
class TextChunk:
    """A chunk of text from the Brain, typically one or more sentences."""
    text: str
    chunk_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    is_final: bool = False


@dataclass
class ToolEvent:
    """Brain started or finished a tool call."""
    name: str
    status: Literal["started", "done"]
    result: str | None = None


@dataclass
class TimedAudio:
    """PCM audio bytes from TTS, optionally with alignment timestamps."""
    audio: bytes
    sample_rate: int
    chunk_id: str = ""
    alignment: dict | None = None
    is_final: bool = False


@dataclass
class PlaybackMarker:
    """AudioPlayer signals when a chunk actually starts playing."""
    chunk_id: str
    wall_time_started: float


@dataclass
class StateChange:
    """Pipeline state transition."""
    state: Literal["idle", "listening", "thinking", "speaking", "interrupted"]


@dataclass
class BufferStatus:
    """AudioPlayer reports how much audio is buffered."""
    depth: int
    seconds_remaining: float


@dataclass
class BodyCue:
    """Body motion cue from the Director."""
    chunk_id: str | None = None
    emotion: str = "neutral"
    energy: float = 0.5
    gesture: str | None = None
    at_word: str | None = None
    offset_ms: int | None = None
