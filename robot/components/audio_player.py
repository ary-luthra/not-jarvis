"""AudioPlayer component: plays TimedAudio, emits sync markers and buffer status."""

import logging
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
    ):
        super().__init__("audio_player")
        self._audio_q = audio_in.subscribe()
        self.state_out = state_out
        self.buffer_out = buffer_out
        self.marker_out = marker_out
        self._stream = None
        self._current_rate = None
        self._total_samples = 0
        self._playback_start = None

    def run(self):
        current_chunk_id = None

        while self.running:
            try:
                item = self._audio_q.get(timeout=0.1)
            except Empty:
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

            # New chunk — emit playback marker and buffer status
            if item.chunk_id != current_chunk_id:
                current_chunk_id = item.chunk_id
                self.state_out.put(StateChange(state="speaking"))
                self.marker_out.put(
                    PlaybackMarker(
                        chunk_id=item.chunk_id,
                        wall_time_started=time.time(),
                    )
                )
                # Report buffer depth
                depth = self._audio_q.qsize()
                remaining = self._estimate_remaining()
                self.buffer_out.put(BufferStatus(depth=depth, seconds_remaining=remaining))
                logger.debug(f"[audio] playing chunk {item.chunk_id} (buf={depth})")

            self._play(item)

    def _estimate_remaining(self) -> float:
        """Estimate seconds of audio remaining in playback buffer."""
        if not self._current_rate or not self._playback_start:
            return 0
        total_duration = self._total_samples / self._current_rate
        elapsed = time.time() - self._playback_start
        remaining = total_duration - elapsed
        return max(0, remaining)

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
