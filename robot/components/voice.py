"""Voice component: consumes TextChunks, produces TimedAudio via ElevenLabs.

Fires TTS requests concurrently in a thread pool so that chunk 2 starts
synthesizing while chunk 1 is still streaming back. Audio is pushed to
audio_out in chunk order via a sequencing layer.
"""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty

from elevenlabs import ElevenLabs

from robot.core import Bus, Component, TextChunk, TimedAudio, EndOfResponse

logger = logging.getLogger(__name__)

MAX_CONCURRENT_TTS = 3


class Voice(Component):
    def __init__(
        self,
        text_in: Bus,
        audio_out: Bus,
        voice_id: str = "cgSgspJ2msm6clMCkdW9",
        model_id: str = "eleven_v3",
    ):
        super().__init__("voice")
        self._text_q = text_in.subscribe()
        self.audio_out = audio_out
        self.voice_id = voice_id
        self.model_id = model_id
        self.client = ElevenLabs(api_key=os.environ.get("ELEVEN_API_KEY"))

    def run(self):
        pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TTS)

        chunk_queues: list[Queue] = []
        lock = threading.Lock()
        drain_done = threading.Event()

        def drain_in_order():
            while not drain_done.is_set() or chunk_queues:
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
            try:
                chunk = self._text_q.get(timeout=0.1)
            except Empty:
                continue

            if not isinstance(chunk, TextChunk):
                continue

            if chunk.text:
                cq = Queue()
                with lock:
                    chunk_queues.append(cq)
                pool.submit(self._synthesize_to_queue, chunk, cq)

            if chunk.is_final:
                pool.shutdown(wait=True)
                pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TTS)
                self.audio_out.put(EndOfResponse())
                logger.debug("[voice] end of response")

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
                if audio_bytes:
                    cq.put(
                        TimedAudio(
                            audio=audio_bytes,
                            sample_rate=16000,
                            chunk_id=chunk.chunk_id,
                        )
                    )
            logger.debug(f"[voice] synthesized: {chunk.text[:60]}...")
        except Exception:
            logger.exception(f"[voice] TTS failed for chunk {chunk.chunk_id}")
        finally:
            cq.put(None)
