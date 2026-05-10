"""Brain component: streams Claude responses, chunks text, handles tool calls.

Chunking strategy based on audio buffer depth (PCM fragment count):
  - <50 fragments: flush at 35 chars — running low
  - 50-200 fragments: flush at 120 chars — comfortable
  - 200+ fragments: flush at 500 chars — deep buffer, accumulate
  - Hard cap at 1000 chars always

Tool use: loops until Claude produces a text-only response. Tools are defined
as decorated Python methods with Google-style docstrings.

On interrupt (StateChange("listening") or StateChange("interrupted")): stops streaming, saves partial response.
"""

import logging
import random
import threading
from queue import Empty
from typing import Literal

import anthropic

from robot.core import (
    BufferStatus,
    Bus,
    Component,
    StateChange,
    TextChunk,
    ToolEvent,
)
import memory as memory_store
from .agent_tools import agent_tool, collect_agent_tools

logger = logging.getLogger(__name__)

URGENT_MIN = 35
LOW_MIN = 120
COMFORTABLE_MIN = 500
CHUNK_MAX_CHARS = 1000

BUF_LOW = 50
BUF_COMFORTABLE = 200

INTERRUPT_ACKS = [
    "Oh, that changes things.",
    "Got it, switching gears.",
    "Sure, forget what I was saying.",
    "Okay, new direction.",
    "Alright, go ahead.",
]


class Brain(Component):
    def __init__(
        self,
        input_bus: Bus,
        text_bus: Bus,
        tool_bus: Bus,
        state_bus: Bus,
        buffer_bus: Bus,
        model: str = "claude-sonnet-4-6",
        system_prompt: str = "",
        current_user: str = "aryan",
    ):
        super().__init__("brain")
        self._input_q = input_bus.subscribe()
        self.text_bus = text_bus
        self.tool_bus = tool_bus
        self.state_bus = state_bus
        self._state_q = state_bus.subscribe()
        self._buffer_q = buffer_bus.subscribe()
        self.model = model
        self.system_prompt = system_prompt
        self.current_user = current_user
        self.client = anthropic.Anthropic()
        self._tool_schemas, self._tool_handlers = collect_agent_tools(self)
        self.conversation_history: list[dict] = []
        self._buffer_depth = 0
        self._interrupted = threading.Event()

    def run(self):
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
        while self.running:
            try:
                event = self._state_q.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(event, StateChange) and event.state in ("listening", "interrupted"):
                self._interrupted.set()
                logger.debug("[brain] interrupted")

    def _process(self, payload):
        if isinstance(payload, dict):
            user_text = payload["text"]
            was_interrupted = payload.get("interrupted", False)
        else:
            user_text = payload
            was_interrupted = False

        self.conversation_history.append({"role": "user", "content": user_text})
        self.state_bus.put(StateChange(state="thinking"))

        if was_interrupted:
            self.text_bus.put(TextChunk(text=random.choice(INTERRUPT_ACKS)))

        logger.info(f"[brain] processing: {user_text[:80]}")

        # Stream Claude, handle tool calls in a loop
        while not self._interrupted.is_set():
            response, text, was_interrupted = self._stream_response()

            if was_interrupted:
                if text:
                    self.conversation_history.append(
                        {"role": "assistant", "content": text}
                    )
                logger.info(f"[brain] interrupted ({len(text)} chars)")
                return

            # Check for tool calls
            tool_use_blocks = [
                block for block in response.content if block.type == "tool_use"
            ]

            if not tool_use_blocks:
                # No tool call — we're done
                if text:
                    self.conversation_history.append(
                        {"role": "assistant", "content": text}
                    )
                logger.info(f"[brain] done ({len(text)} chars)")
                return

            # Save assistant response with tool use to history
            self.conversation_history.append(
                {"role": "assistant", "content": response.content}
            )

            tool_results = []
            for tool_use_block in tool_use_blocks:
                # Handle tool call
                logger.info(f"[brain] tool call: {tool_use_block.name}({tool_use_block.input})")

                # Publish tool event. The model should provide any spoken lead-in
                # itself before using a tool, so we don't inject generic filler here.
                self.tool_bus.put(ToolEvent(name=tool_use_block.name, status="started"))

                # Execute tool
                result = self._execute_tool(tool_use_block.name, tool_use_block.input)

                self.tool_bus.put(ToolEvent(
                    name=tool_use_block.name, status="done", result=result
                ))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,
                    "content": result,
                })

            # Add tool results to history and loop for Claude's follow-up
            self.conversation_history.append({
                "role": "user",
                "content": tool_results,
            })

    def _stream_response(self) -> tuple:
        """Stream one Claude response. Returns (response, full_text, was_interrupted)."""
        buffer = ""
        full_response = ""
        chunks_sent = 0

        with self.client.messages.stream(
            model=self.model,
            max_tokens=2000,
            system=self._build_system_prompt(),
            messages=self.conversation_history,
            tools=self._tool_schemas,
        ) as stream:
            for token in stream.text_stream:
                if self._interrupted.is_set():
                    return None, full_response, True

                buffer += token
                full_response += token

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
                    self.text_bus.put(TextChunk(text=chunk_text))
                    logger.debug(f"[brain] chunk #{chunks_sent} ({len(chunk_text)} chars, buf={self._buffer_depth}): {chunk_text[:60]}...")

            response = stream.get_final_message()

        # Flush remaining text
        has_tool_call = any(block.type == "tool_use" for block in response.content)
        remaining = buffer.strip()
        if remaining:
            self.text_bus.put(TextChunk(text=remaining, is_final=not has_tool_call))
        else:
            self.text_bus.put(TextChunk(text="", is_final=not has_tool_call))

        return response, full_response, False

    def _execute_tool(self, name: str, input_data: dict) -> str:
        """Execute a tool and return the result as a string."""
        handler = self._tool_handlers.get(name)
        if handler:
            return handler(**input_data)
        return f"Unknown tool: {name}"

    def _build_system_prompt(self) -> str:
        """Build the voice prompt with current long-term memory injected."""
        user_memory = memory_store.read_memory(self.current_user)
        home_memory = memory_store.read_home_memory()
        parts = [self.system_prompt.strip()]
        parts.append(
            "You have long-term memory. Relevant memory is loaded below. "
            "Use it naturally, but do not mention that you are reading memory unless asked.\n\n"
            "For complex questions that need deeper reasoning but no external information, "
            "you may use pause_to_think. Before using it, say one brief, natural, "
            "context-specific acknowledgement that names the thing you are thinking through. "
            "After it returns, answer directly. Use it sparingly; do not use it for simple "
            "questions.\n\n"
            "When the user shares stable personal preferences, recurring habits, ongoing "
            "projects, or important facts, call save_memory with scope='user'. "
            "When they share stable facts about the home, robot, devices, routines, or "
            "setup, call save_memory with scope='home'. If they ask a question while "
            "sharing a memory-worthy fact, save the memory and then still answer the question."
        )
        if user_memory:
            parts.append(f"## User Memory ({self.current_user})\n{user_memory.strip()}")
        if home_memory:
            parts.append(f"## Home / Robot Memory\n{home_memory.strip()}")
        return "\n\n".join(part for part in parts if part)

    @agent_tool
    def save_memory(self, scope: Literal["user", "home"], fact: str) -> str:
        """Save a stable fact to long-term memory.

        Use when the user shares personal preferences, recurring habits,
        ongoing projects, important relationships, or stable facts about the
        home/robot setup. Do not save one-off requests, temporary moods, or
        facts that only matter right now.

        Args:
            scope: Use 'user' for facts about the current person. Use 'home'
                for shared facts about the house, robot, devices, routines, or
                setup.
            fact: A short declarative memory. Good: 'Prefers concise answers
                in the morning.' Bad: 'The user told me something.'
        """
        fact = fact.strip()
        if not fact:
            return "Memory not saved: fact was empty."
        if scope == "home":
            return memory_store.save_home_memory(fact)
        if scope == "user":
            return memory_store.save_memory(self.current_user, fact)
        return f"Memory not saved: unknown scope '{scope}'."

    @agent_tool
    def pause_to_think(self, thoughts: str) -> str:
        """Pause for complex reasoning before answering.

        Use when the user asks a complex question that benefits from deeper
        reasoning before answering, but does not need external information.
        Before calling this tool, say one short, natural, context-specific
        acknowledgement out loud that names what you are thinking through.
        Spend as much time thinking here as necessary before continuing. Use
        this sparingly. Do not use it for simple questions.

        Args:
            thoughts: Private notes for the thinking step. Spend as much time
                thinking here as necessary.
        """
        thoughts = thoughts.strip()
        if thoughts:
            logger.info("[brain] pause_to_think: %s", thoughts[:120])
        return "Done thinking. Continue with the answer."

    @agent_tool
    def web_search(self, query: str) -> str:
        """Search the web for current information.

        Use when the user asks about recent events, facts you're unsure about,
        or anything that benefits from up-to-date information.

        Args:
            query: The search query.
        """
        import os
        from tavily import TavilyClient

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return "Web search unavailable — TAVILY_API_KEY not set."

        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(query, max_results=5)
            return response.get("answer", "") or "\n".join(
                r.get("content", "") for r in response.get("results", [])
            )
        except Exception as e:
            logger.exception("[brain] web search failed")
            return f"Search failed: {e}"

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
