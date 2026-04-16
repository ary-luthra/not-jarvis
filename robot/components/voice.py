"""Voice component: consumes TextChunks, produces TimedAudio via ElevenLabs.

Fires TTS requests concurrently. On interruption (StateChange("listening")),
cancels pending TTS and clears queues.
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty

from elevenlabs import ElevenLabs

from robot.core import Bus, Component, TextChunk, TimedAudio, EndOfResponse, StateChange

logger = logging.getLogger(__name__)

MAX_CONCURRENT_TTS = 3


class Voice(Component):
    def __init__(
        self,
        text_in: Bus,
        audio_out: Bus,
        state_in: Bus,
        voice_id: str = "cgSgspJ2msm6clMCkdW9",
        model_id: str = "eleven_v3",
    ):
        super().__init__("voice")
        self._text_q = text_in.subscribe()
        self._state_q = state_in.subscribe()
        self.audio_out = audio_out
        self.voice_id = voice_id
        self.model_id = model_id
        self.client = ElevenLabs(api_key=os.environ.get("ELEVEN_API_KEY"))
        self._interrupted = threading.Event()

    def run(self):
        # Watch for interrupts in background
        interrupt_thread = threading.Thread(target=self._watch_state, daemon=True)
        interrupt_thread.start()

        while self.running:
            self._interrupted.clear()
            self._process_response()

    def _watch_state(self):
        while self.running:
            try:
                event = self._state_q.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(event, StateChange) and event.state == "listening":
                self._interrupted.set()
                logger.debug("[voice] interrupted")

    def _process_response(self):
        """Process one full response worth of TextChunks."""
        pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TTS)
        chunk_queues: list[Queue] = []
        lock = threading.Lock()
        drain_done = threading.Event()

        def drain_in_order():
            while not drain_done.is_set() or chunk_queues:
                if self._interrupted.is_set():
                    # Clear all pending audio
                    with lock:
                        chunk_queues.clear()
                    return
                with lock:
                    if chunk_queues:
                        q = chunk_queues[0]
                        try:
                            item = q.get(timeout=0.05)
                            if item is None:
                                chunk_queues.pop(0)
                            else:
                                self.audio_out.put(item)
                            continue
                        except Empty:
                            pass
                drain_done.wait(timeout=0.05)

        drain_thread = threading.Thread(target=drain_in_order, name="voice-drain", daemon=True)
        drain_thread.start()

        while self.running:
            if self._interrupted.is_set():
                logger.info("[voice] clearing pending TTS")
                # Drain the text queue of remaining chunks for this response
                while not self._text_q.empty():
                    try:
                        self._text_q.get_nowait()
                    except Empty:
                        break
                break

            try:
                chunk = self._text_q.get(timeout=0.1)
            except Empty:
                continue

            if not isinstance(chunk, TextChunk):
                continue

            if chunk.text and not self._interrupted.is_set():
                cq = Queue()
                with lock:
                    chunk_queues.append(cq)
                pool.submit(self._synthesize_to_queue, chunk, cq)

            if chunk.is_final:
                # Wait for all TTS to finish
                pool.shutdown(wait=True)
                pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TTS)

                # Wait for drain to forward all audio
                while not self._interrupted.is_set():
                    with lock:
                        if not chunk_queues:
                            break
                    time.sleep(0.05)

                if not self._interrupted.is_set():
                    self.audio_out.put(EndOfResponse())
                    logger.debug("[voice] end of response")
                break

        drain_done.set()
        pool.shutdown(wait=False)
        drain_thread.join(timeout=2)

    def _synthesize_to_queue(self, chunk: TextChunk, cq: Queue):
        try:
            for audio_bytes in self.client.text_to_speech.stream(
                text=chunk.text,
                voice_id=self.voice_id,
                model_id=self.model_id,
                output_format="pcm_16000",
            ):
                if self._interrupted.is_set():
                    break
                if audio_bytes:
                    cq.put(
                        TimedAudio(
                            audio=audio_bytes,
                            sample_rate=16000,
                            chunk_id=chunk.chunk_id,
                        )
                    )
            if not self._interrupted.is_set():
                logger.debug(f"[voice] synthesized: {chunk.text[:60]}...")
        except Exception:
            logger.exception(f"[voice] TTS failed for chunk {chunk.chunk_id}")
        finally:
            cq.put(None)
