"""Orchestrator: creates buses, wires components."""

import logging

from robot.core import Bus
from robot.components import Brain, Voice, AudioPlayer, Listener, BodyController

logger = logging.getLogger(__name__)

VOICE_SYSTEM_PROMPT = (
    "You are a friendly, conversational AI assistant speaking through a robot. "
    "Remember this is a voice conversation, so there may be issues with transcriptions. "
    "Your responses will be passed through text-to-speech, so format them "
    "as natural spoken language — write numbers and dates in spoken form, use contractions, "
    "and avoid anything that doesn't translate well to speech like markdown. "
    "Be natural and conversational. Keep responses concise."
)


class Orchestrator:
    def __init__(
        self,
        system_prompt: str = VOICE_SYSTEM_PROMPT,
        text_mode: bool = False,
        mini=None,
        current_user: str = "aryan",
        hotword_threshold: float = 0.5,
    ):
        # Buses
        self.input_bus = Bus()
        self.text_bus = Bus()
        self.audio_bus = Bus()
        self.state_bus = Bus()
        self.buffer_bus = Bus()
        self.marker_bus = Bus()
        self.tool_bus = Bus()
        self.cue_bus = Bus()

        # Components — each takes the buses it cares about
        self.brain = Brain(
            input_bus=self.input_bus,
            text_bus=self.text_bus,
            tool_bus=self.tool_bus,
            state_bus=self.state_bus,
            buffer_bus=self.buffer_bus,
            system_prompt=system_prompt,
            current_user=current_user,
        )
        self.voice = Voice(
            text_bus=self.text_bus,
            audio_bus=self.audio_bus,
            state_bus=self.state_bus,
        )
        self.audio_player = AudioPlayer(
            audio_bus=self.audio_bus,
            state_bus=self.state_bus,
            buffer_bus=self.buffer_bus,
            marker_bus=self.marker_bus,
        )

        self._components = [self.brain, self.voice, self.audio_player]

        if not text_mode:
            self.listener = Listener(
                state_bus=self.state_bus,
                input_bus=self.input_bus,
                hotword_threshold=hotword_threshold,
            )
            self._components.append(self.listener)

        if mini:
            self.body = BodyController(
                mini=mini,
                state_bus=self.state_bus,
            )
            self._components.append(self.body)

        # Phase 4: Director(text_bus, state_bus, tool_bus, cue_bus)

    def start(self):
        for c in self._components:
            c.start()
            logger.info(f"started {c.name}")

    def stop(self):
        for c in reversed(self._components):
            c.stop()
            logger.info(f"stopped {c.name}")

    def send(self, user_text: str):
        """Send user input to the brain (text mode only)."""
        self.input_bus.put(user_text)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
