"""Listener component: mic → VAD → record → Whisper → publish transcription.

State machine (never blocks):
  - idle: raw mic → VAD → detect speech → record → transcribe → publish
  - thinking: wait (Brain is working)
  - speaking: mute (skip VAD to avoid self-echo)
             TODO: add hotword detection here for interruption

Publishes:
  - state_bus: StateChange("listening") when user starts speaking
  - input_bus: transcribed text for Brain

Subscribes:
  - state_bus: knows current pipeline state
"""

import logging
import queue as stdlib_queue
import time

import numpy as np
import sounddevice as sd
import torch

from robot.core import Bus, Component, StateChange

logger = logging.getLogger(__name__)

# Audio config
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION_MS = 32          # VAD frame size (512 samples at 16kHz for Silero)

# VAD threshold
VAD_THRESHOLD = 0.5

# Timing
SILENCE_THRESHOLD_S = 0.6
MIN_SPEECH_S = 0.3


class Listener(Component):
    def __init__(
        self,
        state_bus: Bus,
        input_bus: Bus,
        audio_bus: Bus,
        whisper_model_size: str = "base.en",
    ):
        super().__init__("listener")
        self._state_q = state_bus.subscribe()
        self._audio_q = audio_bus.subscribe()  # for future hotword/AEC use
        self.state_bus = state_bus
        self.input_bus = input_bus
        self._current_state = "idle"
        self._whisper_model_size = whisper_model_size
        self._vad_model = None
        self._whisper_model = None

    def _load_models(self):
        logger.info("[listener] loading Silero VAD...")
        self._vad_model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )

        logger.info("[listener] loading Whisper STT...")
        from faster_whisper import WhisperModel
        self._whisper_model = WhisperModel(
            self._whisper_model_size, compute_type="int8", device="cpu"
        )
        logger.info("[listener] models loaded")

    def run(self):
        self._load_models()

        while self.running:
            self._drain_state()

            if self._current_state == "speaking":
                # Mute — skip VAD to avoid hearing ourselves
                # TODO: add hotword detection ("stop", "hey") here
                self._drain_audio_bus()
                time.sleep(0.1)
                continue

            if self._current_state == "thinking":
                time.sleep(0.1)
                continue

            # idle or listening — record speech
            audio = self._record_until_silence()
            if audio is None:
                continue

            text = self._transcribe(audio)
            if not text:
                logger.debug("[listener] empty transcription, ignoring")
                continue

            logger.info(f'[listener] heard: "{text}"')
            self._current_state = "thinking"
            self.state_bus.put(StateChange(state="thinking"))
            self.input_bus.put(text)

    def _drain_state(self):
        while not self._state_q.empty():
            event = self._state_q.get()
            if isinstance(event, StateChange):
                self._current_state = event.state

    def _drain_audio_bus(self):
        """Discard audio bus items (not used yet, prevents queue buildup)."""
        while not self._audio_q.empty():
            self._audio_q.get()

    def _record_until_silence(self) -> np.ndarray | None:
        audio_q = stdlib_queue.Queue()
        block_size = int(SAMPLE_RATE * BLOCK_DURATION_MS / 1000)

        def callback(indata, frames, time_info, status):
            audio_q.put(indata[:, 0].copy())

        frames = []
        is_speaking = False
        silence_frames = 0
        speech_frames = 0
        silence_limit = int(SILENCE_THRESHOLD_S * 1000 / BLOCK_DURATION_MS)
        min_speech_limit = int(MIN_SPEECH_S * 1000 / BLOCK_DURATION_MS)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=block_size,
            callback=callback,
        ):
            while self.running:
                try:
                    chunk = audio_q.get(timeout=0.1)
                except stdlib_queue.Empty:
                    continue

                frames.append(chunk)
                self._drain_state()

                # Mute if robot started speaking/thinking
                if self._current_state in ("speaking", "thinking"):
                    frames.clear()
                    is_speaking = False
                    silence_frames = 0
                    speech_frames = 0
                    continue

                chunk_tensor = torch.from_numpy(chunk).float()
                speech_prob = self._vad_model(chunk_tensor, SAMPLE_RATE).item()

                if speech_prob > VAD_THRESHOLD:
                    if not is_speaking:
                        is_speaking = True
                        self.state_bus.put(StateChange(state="listening"))
                        logger.debug(f"[listener] speech detected (prob={speech_prob:.2f})")
                    silence_frames = 0
                    speech_frames += 1
                elif is_speaking:
                    silence_frames += 1
                    if silence_frames >= silence_limit and speech_frames >= min_speech_limit:
                        break

        if not is_speaking or speech_frames < min_speech_limit:
            return None

        audio = np.concatenate(frames)
        logger.debug(f"[listener] captured {len(audio) / SAMPLE_RATE:.1f}s of audio")
        return audio

    def _transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self._whisper_model.transcribe(
            audio, beam_size=1, language="en"
        )
        return " ".join(seg.text for seg in segments).strip()
