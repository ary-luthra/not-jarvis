"""Brain component: streams Claude responses, chunks text, emits TextChunks.

Chunking strategy based on audio buffer depth:
  - Buffer empty (0 items): flush at 75 chars — speaker is starving
  - Buffer has 1 item: flush at 150 chars — running low
  - Buffer has 2+ items: flush at 750 chars — plenty buffered, accumulate
  - Hard cap at 1000 chars always
"""

import logging
from queue import Empty

import anthropic

from robot.core import Bus, Component, TextChunk, BufferStatus, StateChange

logger = logging.getLogger(__name__)

URGENT_MIN = 75          # audio buffer empty — speaker is starving
LOW_MIN = 150            # audio buffer has 1 item — running low
COMFORTABLE_MIN = 750    # audio buffer has 2+ items — take your time
CHUNK_MAX_CHARS = 1000   # hard cap


class Brain(Component):
    def __init__(
        self,
        input_in: Bus,
        text_out: Bus,
        tool_out: Bus,
        state_out: Bus,
        buffer_in: Bus,
        model: str = "claude-sonnet-4-20250514",
        system_prompt: str = "",
    ):
        super().__init__("brain")
        self._input_q = input_in.subscribe()
        self.text_out = text_out
        self.tool_out = tool_out
        self.state_out = state_out
        self._buffer_q = buffer_in.subscribe()
        self.model = model
        self.system_prompt = system_prompt
        self.client = anthropic.Anthropic()
        self.conversation_history: list[dict] = []
        self._last_buffer_depth = 0

    def run(self):
        while self.running:
            try:
                user_text = self._input_q.get(timeout=0.1)
            except Empty:
                continue
            self._process(user_text)

    def _process(self, user_text: str):
        self.conversation_history.append({"role": "user", "content": user_text})
        self.state_out.put(StateChange(state="thinking"))
        logger.info(f"[brain] processing: {user_text[:80]}")

        buffer = ""
        full_response = ""
        chunks_sent = 0

        with self.client.messages.stream(
            model=self.model,
            max_tokens=2000,
            system=self.system_prompt,
            messages=self.conversation_history,
        ) as stream:
            for token in stream.text_stream:
                buffer += token
                full_response += token

                # Drain buffer status updates (non-blocking)
                while not self._buffer_q.empty():
                    status = self._buffer_q.get()
                    if isinstance(status, BufferStatus):
                        self._last_buffer_depth = status.depth

                if self._last_buffer_depth == 0:
                    min_chars = URGENT_MIN
                elif self._last_buffer_depth == 1:
                    min_chars = LOW_MIN
                else:
                    min_chars = COMFORTABLE_MIN

                result = self._try_flush(buffer, min_chars)
                if result:
                    chunk_text, buffer = result
                    chunks_sent += 1
                    self.text_out.put(TextChunk(text=chunk_text))
                    logger.debug(f"[brain] chunk #{chunks_sent} ({len(chunk_text)} chars, buf={self._last_buffer_depth}): {chunk_text[:60]}...")

        # Flush whatever remains
        remaining = buffer.strip()
        if remaining:
            self.text_out.put(TextChunk(text=remaining, is_final=True))
        else:
            self.text_out.put(TextChunk(text="", is_final=True))

        self.conversation_history.append(
            {"role": "assistant", "content": full_response}
        )
        logger.info(f"[brain] done ({len(full_response)} chars, {chunks_sent} chunks)")

    def _try_flush(self, buffer: str, min_chars: int) -> tuple[str, str] | None:
        """Extract a chunk from buffer at a sentence boundary."""
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
