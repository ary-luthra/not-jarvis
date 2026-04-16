"""AudioPlayer component: plays TimedAudio, emits sync markers and buffer status.

On interruption (StateChange("listening")), stops playback and clears queue.
"""

import logging
import threading
import time
from queue import Empty

import numpy as np
import sounddevice as sd

from robot.core import (
    Bus, Component, TimedAudio, EndOfResponse,
    PlaybackMarker, StateChange, BufferStatus,
)

logger = logging.getLogger(__name__)


class AudioPlayer(Component):
    def __init__(
        self,
        audio_in: Bus,
        state_out: Bus,
        buffer_out: Bus,
        marker_out: Bus,
        state_in: Bus,
    ):
        super().__init__("audio_player")
        self._audio_q = audio_in.subscribe()
        self._state_q = state_in.subscribe()
        self.state_out = state_out
        self.buffer_out = buffer_out
        self.marker_out = marker_out
        self._stream = None
        self._current_rate = None
        self._total_samples = 0
        self._playback_start = None
        self._interrupted = threading.Event()

    def run(self):
        # Watch for interrupts in background
        interrupt_thread = threading.Thread(target=self._watch_state, daemon=True)
        interrupt_thread.start()

        current_chunk_id = None

        while self.running:
            # Check for interrupt
            if self._interrupted.is_set():
                self._handle_interrupt()
                current_chunk_id = None
                self._interrupted.clear()
                continue

            try:
                item = self._audio_q.get(timeout=0.1)
            except Empty:
                continue

            if self._interrupted.is_set():
                continue

            if isinstance(item, EndOfResponse):
                self._drain()
                self.state_out.put(StateChange(state="idle"))
                self.buffer_out.put(BufferStatus(depth=0, seconds_remaining=0))
                current_chunk_id = None
                logger.debug("[audio] idle")
                continue

            if not isinstance(item, TimedAudio):
                continue

            if item.chunk_id != current_chunk_id:
                current_chunk_id = item.chunk_id
                self.state_out.put(StateChange(state="speaking"))
                self.marker_out.put(
                    PlaybackMarker(
                        chunk_id=item.chunk_id,
                        wall_time_started=time.time(),
                    )
                )
                depth = self._audio_q.qsize()
                self.buffer_out.put(BufferStatus(depth=depth, seconds_remaining=0))
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
        """Stop playback and clear queued audio."""
        logger.info("[audio] interrupted — stopping playback")
        self._close_stream()
        # Drain the audio queue
        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except Empty:
                break
        self._total_samples = 0
        self._playback_start = None

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
