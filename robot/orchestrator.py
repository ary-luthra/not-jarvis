"""Orchestrator: creates buses, wires components."""

import logging

from robot.core import Bus
from robot.components import Brain, Voice, AudioPlayer

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
    def __init__(self, system_prompt: str = VOICE_SYSTEM_PROMPT, mini=None):
        # Buses
        self.input_bus = Bus()
        self.text_bus = Bus()
        self.audio_bus = Bus()
        self.state_bus = Bus()
        self.buffer_bus = Bus()
        self.marker_bus = Bus()
        self.tool_bus = Bus()
        self.cue_bus = Bus()

        # Components
        self.brain = Brain(
            input_in=self.input_bus,
            text_out=self.text_bus,
            tool_out=self.tool_bus,
            state_out=self.state_bus,
            buffer_in=self.buffer_bus,
            system_prompt=system_prompt,
        )
        self.voice = Voice(
            text_in=self.text_bus,
            audio_out=self.audio_bus,
        )
        self.audio_player = AudioPlayer(
            audio_in=self.audio_bus,
            state_out=self.state_bus,
            buffer_out=self.buffer_bus,
            marker_out=self.marker_bus,
        )

        self._components = [self.brain, self.voice, self.audio_player]

        # Phase 2: BodyController subscribes to state_bus, cue_bus, marker_bus
        # Phase 4: Director subscribes to text_bus, state_bus, tool_bus; publishes to cue_bus

    def start(self):
        for c in self._components:
            c.start()
            logger.info(f"started {c.name}")

    def stop(self):
        for c in reversed(self._components):
            c.stop()
            logger.info(f"stopped {c.name}")

    def send(self, user_text: str):
        """Send user input to the brain."""
        self.input_bus.put(user_text)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
