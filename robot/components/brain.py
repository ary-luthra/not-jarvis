"""Brain component: streams Claude responses, chunks text, emits TextChunks.

Chunking strategy based on audio buffer depth (PCM fragment count):
  - <50 fragments (~few seconds): flush at 75 chars — running low
  - 50-200 fragments: flush at 150 chars — comfortable
  - 200+ fragments: flush at 750 chars — deep buffer, accumulate
  - Hard cap at 1000 chars always

Interruption: subscribes to state_bus. On StateChange("listening"),
stops streaming and saves partial response to conversation history.
"""

import logging
import threading
from queue import Empty

import anthropic

from robot.core import Bus, Component, TextChunk, BufferStatus, StateChange

logger = logging.getLogger(__name__)

URGENT_MIN = 75
LOW_MIN = 150
COMFORTABLE_MIN = 750
CHUNK_MAX_CHARS = 1000

BUF_LOW = 50
BUF_COMFORTABLE = 200


class Brain(Component):
    def __init__(
        self,
        input_in: Bus,
        text_out: Bus,
        tool_out: Bus,
        state_out: Bus,
        buffer_in: Bus,
        state_in: Bus,
        model: str = "claude-sonnet-4-20250514",
        system_prompt: str = "",
    ):
        super().__init__("brain")
        self._input_q = input_in.subscribe()
        self.text_out = text_out
        self.tool_out = tool_out
        self.state_out = state_out
        self._buffer_q = buffer_in.subscribe()
        self._state_q = state_in.subscribe()
        self.model = model
        self.system_prompt = system_prompt
        self.client = anthropic.Anthropic()
        self.conversation_history: list[dict] = []
        self._buffer_depth = 0
        self._interrupted = threading.Event()

    def run(self):
        # Background thread to watch for interrupts
        interrupt_thread = threading.Thread(target=self._watch_state, daemon=True)
        interrupt_thread.start()

        while self.running:
            try:
                user_text = self._input_q.get(timeout=0.1)
            except Empty:
                continue
            self._interrupted.clear()
            self._process(user_text)

    def _watch_state(self):
        """Watch state bus for interruption signals."""
        while self.running:
            try:
                event = self._state_q.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(event, StateChange) and event.state == "listening":
                self._interrupted.set()
                logger.debug("[brain] interrupted")

    def _process(self, user_text: str):
        self.conversation_history.append({"role": "user", "content": user_text})
        self.state_out.put(StateChange(state="thinking"))
        logger.info(f"[brain] processing: {user_text[:80]}")

        buffer = ""
        full_response = ""
        chunks_sent = 0
        was_interrupted = False

        with self.client.messages.stream(
            model=self.model,
            max_tokens=2000,
            system=self.system_prompt,
            messages=self.conversation_history,
        ) as stream:
            for token in stream.text_stream:
                if self._interrupted.is_set():
                    was_interrupted = True
                    logger.info("[brain] stopping stream (interrupted)")
                    break

                buffer += token
                full_response += token

                # Drain buffer status updates (non-blocking)
                while not self._buffer_q.empty():
                    status = self._buffer_q.get()
                    if isinstance(status, BufferStatus):
                        self._buffer_depth = status.depth

                if self._buffer_depth < BUF_LOW:
                    min_chars = URGENT_MIN
                elif self._buffer_depth < BUF_COMFORTABLE:
                    min_chars = LOW_MIN
                else:
                    min_chars = COMFORTABLE_MIN

                result = self._try_flush(buffer, min_chars)
                if result:
                    chunk_text, buffer = result
                    chunks_sent += 1
                    self.text_out.put(TextChunk(text=chunk_text))
                    logger.debug(f"[brain] chunk #{chunks_sent} ({len(chunk_text)} chars, buf={self._buffer_depth}): {chunk_text[:60]}...")

        if not was_interrupted:
            # Normal finish — flush remaining and signal end
            remaining = buffer.strip()
            if remaining:
                self.text_out.put(TextChunk(text=remaining, is_final=True))
            else:
                self.text_out.put(TextChunk(text="", is_final=True))

        # Save whatever we generated (partial or full) to history
        if full_response:
            self.conversation_history.append(
                {"role": "assistant", "content": full_response}
            )

        status = "interrupted" if was_interrupted else "done"
        logger.info(f"[brain] {status} ({len(full_response)} chars, {chunks_sent} chunks)")

    def _try_flush(self, buffer: str, min_chars: int) -> tuple[str, str] | None:
        search_region = buffer[:CHUNK_MAX_CHARS]
        boundary = -1
        for i, ch in enumerate(search_region):
            if ch in ".!?":
                boundary = i + 1
        if boundary < min_chars:
            return None
        chunk = buffer[:boundary].strip()
        remaining = buffer[boundary:]
        return (chunk, remaining) if chunk else None
