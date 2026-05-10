"""AudioPlayer component: plays TimedAudio, emits sync markers and buffer status.

Owns the speaking → idle transition. When audio queue goes dry for 0.5s
after playing, transitions to idle. On interrupt: stops immediately.
"""

import logging
import threading
import time
from queue import Empty

import numpy as np
import sounddevice as sd

from robot.core import (
    Bus, Component, TimedAudio,
    PlaybackMarker, StateChange, BufferStatus,
)

logger = logging.getLogger(__name__)

IDLE_TIMEOUT = 0.5  # seconds of empty queue before transitioning to idle


class AudioPlayer(Component):
    def __init__(
        self,
        audio_bus: Bus,
        state_bus: Bus,
        buffer_bus: Bus,
        marker_bus: Bus,
    ):
        super().__init__("audio_player")
        self._audio_q = audio_bus.subscribe()
        self._state_q = state_bus.subscribe()
        self.state_bus = state_bus
        self.buffer_bus = buffer_bus
        self.marker_bus = marker_bus
        self._stream = None
        self._current_rate = None
        self._total_samples = 0
        self._playback_start = None
        self._interrupted = threading.Event()
        self._is_speaking = False
        self._final_audio_seen = False

    def run(self):
        interrupt_thread = threading.Thread(target=self._watch_state, daemon=True)
        interrupt_thread.start()

        current_chunk_id = None

        while self.running:
            if self._interrupted.is_set():
                self._handle_interrupt()
                current_chunk_id = None
                self._interrupted.clear()
                continue

            try:
                item = self._audio_q.get(timeout=IDLE_TIMEOUT)
            except Empty:
                # Queue has been dry — if we were speaking, we're done
                if self._is_speaking:
                    self._drain()
                    self._is_speaking = False
                    next_state = "idle" if self._final_audio_seen else "thinking"
                    self.state_bus.put(StateChange(state=next_state))
                    self.buffer_bus.put(BufferStatus(depth=0, seconds_remaining=0))
                    current_chunk_id = None
                    self._final_audio_seen = False
                    logger.debug(f"[audio] {next_state}")
                continue

            if self._interrupted.is_set():
                continue

            if not isinstance(item, TimedAudio):
                continue

            if item.is_final:
                self._final_audio_seen = True
                if not self._is_speaking:
                    self.state_bus.put(StateChange(state="idle"))
                    self._final_audio_seen = False
                continue

            # First audio or new chunk — emit markers
            if item.chunk_id != current_chunk_id:
                current_chunk_id = item.chunk_id
                if not self._is_speaking:
                    self._is_speaking = True
                    self._final_audio_seen = False
                    self.state_bus.put(StateChange(state="speaking"))
                self.marker_bus.put(
                    PlaybackMarker(
                        chunk_id=item.chunk_id,
                        wall_time_started=time.time(),
                    )
                )
                depth = self._audio_q.qsize()
                self.buffer_bus.put(BufferStatus(depth=depth, seconds_remaining=0))
                logger.debug(f"[audio] playing chunk {item.chunk_id} (buf={depth})")

            self._play(item)

    def _watch_state(self):
        while self.running:
            try:
                event = self._state_q.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(event, StateChange) and event.state == "listening":
                self._interrupted.set()
                logger.debug("[audio] interrupt signal received")

    def _handle_interrupt(self):
        logger.info("[audio] interrupted — stopping playback")
        self._close_stream()
        self._is_speaking = False
        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except Empty:
                break
        self._total_samples = 0
        self._playback_start = None
        self._final_audio_seen = False

    def _play(self, item: TimedAudio):
        audio = np.frombuffer(item.audio, dtype=np.int16).astype(np.float32) / 32767

        if self._stream is None or self._current_rate != item.sample_rate:
            self._close_stream()
            out_dev = sd.default.device[1]
            if out_dev is not None:
                out_channels = sd.query_devices(out_dev)["max_output_channels"]
            else:
                out_channels = 1
            self._stream = sd.OutputStream(
                samplerate=item.sample_rate,
                channels=out_channels,
                dtype="float32",
            )
            self._stream.start()
            self._current_rate = item.sample_rate
            self._total_samples = 0
            self._playback_start = time.time()

        if self._stream.channels > 1 and audio.ndim == 1:
            audio = np.column_stack([audio] * self._stream.channels)
        elif audio.ndim == 1:
            audio = audio.reshape(-1, 1)

        self._stream.write(audio)
        self._total_samples += audio.shape[0]

    def _drain(self):
        if self._stream and self._current_rate and self._playback_start:
            total_duration = self._total_samples / self._current_rate
            elapsed = time.time() - self._playback_start
            remaining = total_duration - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _close_stream(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def stop(self):
        self._drain()
        self._close_stream()
        super().stop()
