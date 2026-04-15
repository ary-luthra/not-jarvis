"""
Real-time voice conversation loop:
  Mic (Silero VAD) → Whisper STT → Claude → ElevenLabs TTS → Speaker

Usage:
  export ANTHROPIC_API_KEY=...
  export ELEVEN_API_KEY=...
  python test_llm.py --local    # Use Mac mic + speakers for testing
  python test_llm.py            # Use Reachy Mini hardware (default)
"""

import argparse
import os
import queue
import tempfile
import threading
import time
import wave
from pathlib import Path
from dotenv import load_dotenv
import numpy as np
import sounddevice as sd
import torch
import anthropic
from elevenlabs import ElevenLabs

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Args ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--local", action="store_true", help="Use Mac mic + speakers instead of Reachy hardware")
args = parser.parse_args()

LOCAL_MODE = args.local

# ── Audio device selection ────────────────────────────────────────────────────
if not LOCAL_MODE:
    # Find Reachy by name (device indices can shift between runs)
    reachy_dev = None
    for i, d in enumerate(sd.query_devices()):
        if "Reachy" in d["name"]:
            reachy_dev = i
            break
    if reachy_dev is not None:
        sd.default.device = (reachy_dev, reachy_dev)
        print(f"Audio: [{reachy_dev}] {sd.query_devices(reachy_dev)['name']}")
    else:
        print("WARNING: Reachy audio device not found, using system defaults")

# ── Config ────────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION_MS = 32        # VAD frame size (exactly 512 samples at 16kHz for Silero)
SILENCE_THRESHOLD_S = 0.6     # How long silence before we consider speech done
MIN_SPEECH_S = 0.3            # Ignore very short bursts
IDLE_TIMEOUT_S = 30           # Exit if no speech detected for this long
CLAUDE_MODEL = "claude-sonnet-4-20250514"
ELEVEN_VOICE_ID = "cgSgspJ2msm6clMCkdW9"  # Jessica - Playful, Bright, Warm
CHUNK_MIN_CHARS = 100
CHUNK_MAX_CHARS = 500

# ── Clients ───────────────────────────────────────────────────────────────────
claude = anthropic.Anthropic()
eleven = ElevenLabs(api_key=os.environ["ELEVEN_API_KEY"])

if not LOCAL_MODE:
    from reachy_mini import ReachyMini


# ── Load Silero VAD ──────────────────────────────────────────────────────────
print("Loading Silero VAD...")
vad_model, vad_utils = torch.hub.load(
    repo_or_dir="snakers4/silero-vad", model="silero_vad", trust_repo=True
)
(get_speech_timestamps, _, read_audio, _, _) = vad_utils

# ── Load Whisper STT ─────────────────────────────────────────────────────────
print("Loading Whisper STT (this may take a moment on first run)...")
from faster_whisper import WhisperModel

whisper_model = WhisperModel("base.en", compute_type="int8", device="cpu")

# ── Conversation state ───────────────────────────────────────────────────────
conversation_history = []
SYSTEM_PROMPT = (
    "You are a friendly, conversational AI assistant speaking through a robot. "
    "Remember this is a voice conversation, so there may be issues with transcriptions. "
    "Your responses will be passed through ElevenLabs text-to-speech (v3), so format them "
    "as natural spoken language — write numbers and dates in spoken form, use contractions, "
    "and avoid anything that doesn't translate well to speech like markdown. "
    "Be natural and conversational. "
    "You can use audio tags in [brackets] to add expressiveness — any natural description works, "
    "like [whispers], [laughs softly], [thoughtful pause], [excited], [sad and reflective], etc. "
    "Place the tag before the text it affects. Examples:\n"
    '- "So I went to the store and [whispers] I saw the most incredible thing, [normal] but anyway, that\'s a story for later."\n'
    '- "[laughs] I can\'t believe that actually happened. [sighs] But honestly, it\'s kind of bittersweet."\n'
    '- "And then he said [long pause] nothing. Absolutely nothing."\n'
    "Use [normal] to return to your regular voice after a tag that could bleed into the next sentence. "
    "Use these when they genuinely add to the delivery. Also use this to sounds as human as possible without overdoing it."
)



def record_until_silence():
    """Record from mic, using VAD to detect when the user stops speaking.
    Returns numpy audio array, or None if no speech detected within IDLE_TIMEOUT_S."""
    audio_queue = queue.Queue()
    block_size = int(SAMPLE_RATE * BLOCK_DURATION_MS / 1000)

    def callback(indata, frames, time_info, status):
        audio_queue.put(indata[:, 0].copy())

    frames = []
    is_speaking = False
    silence_frames = 0
    speech_frames = 0
    total_frames = 0
    silence_limit = int(SILENCE_THRESHOLD_S * 1000 / BLOCK_DURATION_MS)
    min_speech_limit = int(MIN_SPEECH_S * 1000 / BLOCK_DURATION_MS)
    idle_limit = int(IDLE_TIMEOUT_S * 1000 / BLOCK_DURATION_MS)

    print("\n🎤 Listening... (speak now)")

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=block_size,
        callback=callback,
    ):
        while True:
            chunk = audio_queue.get()
            frames.append(chunk)
            total_frames += 1

            # Timeout if no speech for too long
            if not is_speaking and total_frames >= idle_limit:
                return None

            # Run VAD on this chunk
            chunk_tensor = torch.from_numpy(chunk).float()
            speech_prob = vad_model(chunk_tensor, SAMPLE_RATE).item()

            if speech_prob > 0.5:
                is_speaking = True
                silence_frames = 0
                speech_frames += 1
            elif is_speaking:
                silence_frames += 1
                if silence_frames >= silence_limit and speech_frames >= min_speech_limit:
                    break

    audio = np.concatenate(frames)
    print(f"   Captured {len(audio) / SAMPLE_RATE:.1f}s of audio")
    return audio


def transcribe(audio: np.ndarray) -> str:
    """Transcribe audio using faster-whisper."""
    segments, _ = whisper_model.transcribe(audio, beam_size=1, language="en")
    return " ".join(seg.text for seg in segments).strip()


def _play_audio_worker(audio_queue, spoken_event):
    """Background thread: plays audio via sounddevice (device set at startup)."""
    stream = None
    current_rate = None
    total_samples = 0
    start_time = None
    try:
        while True:
            item = audio_queue.get()
            if item is None:
                break
            if item == "CHUNK_DONE":
                if stream is not None and current_rate is not None:
                    n_samples = int(current_rate * 0.15)
                    silence = np.zeros((n_samples, stream.channels), dtype=np.float32)
                    stream.write(silence)
                    total_samples += n_samples
                spoken_event.set()
                continue
            sample_rate, chunk = item
            audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32767
            if stream is None or current_rate != sample_rate:
                if stream is not None:
                    stream.stop()
                    stream.close()
                out_channels = sd.query_devices(sd.default.device[1])['max_output_channels']
                stream = sd.OutputStream(samplerate=sample_rate, channels=out_channels, dtype="float32")
                stream.start()
                current_rate = sample_rate
                start_time = time.time()
                total_samples = 0
            if stream.channels > 1 and audio_np.ndim == 1:
                audio_np = np.column_stack([audio_np] * stream.channels)
            stream.write(audio_np)
            total_samples += len(audio_np) if audio_np.ndim == 1 else audio_np.shape[0]
    finally:
        # Wait for device to finish playing buffered audio before closing
        if stream is not None and current_rate and start_time:
            total_duration = total_samples / current_rate
            elapsed = time.time() - start_time
            remaining = total_duration - elapsed
            if remaining > 0:
                time.sleep(remaining)
            stream.stop()
            stream.close()


def _find_last_sentence_boundary(text):
    """Return index after the last sentence-ending punctuation, or -1 if none."""
    last = -1
    for i, ch in enumerate(text):
        if ch in ".!?":
            last = i + 1
    return last


import re
import base64
import cv2

AUDIO_TAG_RE = re.compile(r'\[[a-z][a-z ]*\]')

# ── Tool definitions ─────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "take_photo",
        "description": "Take a photo using the robot's camera. Use this when the user asks you to look at something, identify something, count fingers, read text, or anything that requires vision.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

_reachy_mini = None  # set in main() so tools can access it

def _take_photo():
    """Capture a frame from the Reachy camera, return as base64 JPEG."""
    if _reachy_mini is None:
        return None
    frame = _reachy_mini.media.get_frame()
    if frame is None:
        return None
    _, jpeg = cv2.imencode(".jpg", frame)
    return base64.standard_b64encode(jpeg.tobytes()).decode("utf-8")


def _strip_audio_tags(text):
    """Remove v3 audio tags from text for flash v2.5."""
    return AUDIO_TAG_RE.sub('', text).strip()


def _tts_flash(text, previous_text=None):
    """Fast TTS via flash v2.5. Strips audio tags. Returns list of (sample_rate, pcm_bytes)."""
    chunks = []
    kwargs = dict(
        text=_strip_audio_tags(text),
        voice_id=ELEVEN_VOICE_ID,
        model_id="eleven_flash_v2_5",
        output_format="pcm_16000",
    )
    if previous_text:
        kwargs["previous_text"] = _strip_audio_tags(previous_text)
    for chunk in eleven.text_to_speech.stream(**kwargs):
        if chunk:
            chunks.append((16000, chunk))
    return chunks


def _tts_v3(text):
    """Expressive TTS via v3 with audio tags. Returns list of (sample_rate, pcm_bytes)."""
    chunks = []
    for chunk in eleven.text_to_speech.stream(
        text=text,
        voice_id=ELEVEN_VOICE_ID,
        model_id="eleven_v3",
        output_format="pcm_16000",
    ):
        if chunk:
            chunks.append((16000, chunk))
    return chunks


def _call_claude_with_tools(messages):
    """Call Claude in a tool-use loop. Returns the final text response."""
    while True:
        response = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )

        tool_use_block = None
        text_parts = []
        for block in response.content:
            if block.type == "tool_use":
                tool_use_block = block
            elif block.type == "text":
                text_parts.append(block.text)

        if tool_use_block is None:
            return " ".join(text_parts)

        # Handle tool call
        print(f"   📸 Using tool: {tool_use_block.name}")

        if tool_use_block.name == "take_photo":
            photo_b64 = _take_photo()
            if photo_b64 is None:
                tool_result_content = [{"type": "text", "text": "Camera not available."}]
            else:
                tool_result_content = [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": photo_b64}},
                    {"type": "text", "text": "Here is what I see from my camera."},
                ]
        else:
            tool_result_content = [{"type": "text", "text": f"Unknown tool: {tool_use_block.name}"}]

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_block.id, "content": tool_result_content}]})


def stream_claude_to_tts(user_text: str, mini=None):
    """Baseball model: home plate (speaking), on deck (TTS'd), in the hole (text buffer).

    - Speaker finishes a chunk → on-deck audio starts playing
    - Biggest possible text chunk is pulled from buffer → sent to TTS → becomes new on-deck
    """
    conversation_history.append({"role": "user", "content": user_text})
    print("   🧠 Thinking...")

    audio_queue = queue.Queue()
    spoken_event = threading.Event()
    play_thread = threading.Thread(target=_play_audio_worker, args=(audio_queue, spoken_event))
    play_thread.start()

    full_response = ""
    buffer = ""
    chunks_log = []
    on_deck = None
    on_deck_thread = None

    def flush_buffer(force=False):
        """Extract a chunk from buffer respecting min/max char limits.

        - Won't flush unless buffer has >= CHUNK_MIN_CHARS at a sentence boundary
          (unless force=True for the final flush)
        - Won't exceed CHUNK_MAX_CHARS — splits at last sentence boundary before the cap
        - force=True skips the floor but still respects the ceiling
        """
        nonlocal buffer
        # Find the right boundary: last sentence end within CHUNK_MAX_CHARS
        search_region = buffer[:CHUNK_MAX_CHARS]
        boundary = _find_last_sentence_boundary(search_region)
        if boundary <= 0:
            if force and buffer.strip():
                # No sentence boundary — take up to ceiling anyway
                to_send = buffer[:CHUNK_MAX_CHARS].strip()
                buffer = buffer[CHUNK_MAX_CHARS:]
                return to_send if to_send else None
            return None
        # Check floor (unless forced)
        if boundary < CHUNK_MIN_CHARS and not force:
            return None
        to_send = buffer[:boundary].strip()
        buffer = buffer[boundary:]
        return to_send if to_send else None

    def play_on_deck():
        """Wait for on-deck TTS to finish, push its audio to the speaker."""
        nonlocal on_deck, on_deck_thread
        if on_deck_thread is not None:
            on_deck_thread.join()
            for item in on_deck:
                audio_queue.put(item)
            audio_queue.put("CHUNK_DONE")
            on_deck = None
            on_deck_thread = None

    last_chunk_text = None  # for previous_text stitching on flash

    def start_on_deck(text):
        """Start TTS processing for on-deck in a background thread."""
        nonlocal on_deck, on_deck_thread
        chunks_log.append(text)
        result = []
        def do_tts():
            result.extend(_tts_v3(text))
        on_deck_thread = threading.Thread(target=do_tts)
        on_deck_thread.start()
        on_deck = result

    # ── Play thinking sound while waiting for first chunk ─────────────────────
    thinking_audio = _tts_flash("-- Hmmmmmmm...")
    for item in thinking_audio:
        audio_queue.put(item)

    # ── Stream Claude (with tool-use loop) ────────────────────────────────────
    tool_use_messages = list(conversation_history)
    use_tools = not LOCAL_MODE and _reachy_mini is not None
    first_sent = False
    second_sent = False

    while True:
        with claude.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=tool_use_messages,
            tools=TOOLS if use_tools else [],
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                buffer += text
                print(text, end="", flush=True)

                if not first_sent:
                    chunk = flush_buffer()
                    if chunk:
                        chunks_log.append(chunk)
                        audio = _tts_flash(chunk)
                        for item in audio:
                            audio_queue.put(item)
                        audio_queue.put("CHUNK_DONE")
                        last_chunk_text = chunk
                        first_sent = True

                elif not second_sent:
                    chunk = flush_buffer()
                    if chunk:
                        start_on_deck(chunk)
                        second_sent = True

                else:
                    if spoken_event.is_set():
                        spoken_event.clear()
                        play_on_deck()
                        chunk = flush_buffer()
                        if chunk:
                            start_on_deck(chunk)

            # Check if Claude called a tool
            response = stream.get_final_message()

        tool_use_block = None
        for block in response.content:
            if block.type == "tool_use":
                tool_use_block = block
                break

        if tool_use_block is None:
            break  # No tool call, we're done

        # Handle tool call
        print(f"\n   📸 Using tool: {tool_use_block.name}")
        if tool_use_block.name == "take_photo":
            photo_b64 = _take_photo()
            if photo_b64 is None:
                print("   ❌ Camera not available")
                tool_result_content = [{"type": "text", "text": "Camera not available."}]
            else:
                # Save photo to temp file and show path
                photo_path = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="reachy_photo_").name
                with open(photo_path, "wb") as f:
                    f.write(base64.standard_b64decode(photo_b64))
                print(f"   📷 Photo saved: {photo_path}")
                # Open in Preview (macOS)
                import subprocess
                subprocess.Popen(["open", photo_path])
                tool_result_content = [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": photo_b64}},
                    {"type": "text", "text": "Here is what I see from my camera."},
                ]
        else:
            tool_result_content = [{"type": "text", "text": f"Unknown tool: {tool_use_block.name}"}]

        # Add to messages and loop for Claude's follow-up response
        tool_use_messages.append({"role": "assistant", "content": response.content})
        tool_use_messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_block.id, "content": tool_result_content}]})
        full_response = ""  # reset — the follow-up is the real response
        buffer = ""

    # ── Drain everything ──────────────────────────────────────────────────────

    play_on_deck()

    while buffer.strip():
        chunk = flush_buffer(force=True)
        if not chunk:
            break
        chunks_log.append(chunk)
        audio = _tts_v3(chunk)
        for item in audio:
            audio_queue.put(item)
        audio_queue.put("CHUNK_DONE")

    audio_queue.put(None)
    play_thread.join()

    print()
    print("\n   ── Chunking Log ──")
    print(f"   Full response ({len(full_response)} chars):")
    print(f"   {full_response[:100]}{'...' if len(full_response) > 100 else ''}")
    print(f"   Chunks sent to TTS: {len(chunks_log)}")
    for i, chunk in enumerate(chunks_log):
        print(f"     [{i+1}] ({len(chunk)} chars) {chunk[:80]}{'...' if len(chunk) > 80 else ''}")
    print("   ── End Log ──\n")

    conversation_history.append({"role": "assistant", "content": full_response})



def conversation_loop(mini=None):
    """Main loop: listen → transcribe → think → speak."""
    while True:
        try:
            audio = record_until_silence()

            if audio is None:
                print(f"\n   No speech detected for {IDLE_TIMEOUT_S}s. Ending conversation.")
                break

            print("   📝 Transcribing...")
            text = transcribe(audio)
            if not text:
                print("   (no speech detected, trying again)")
                continue
            print(f'   You: "{text}"')

            stream_claude_to_tts(text, mini=mini)

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break


def main():
    mode = "LOCAL (Mac mic + speakers)" if LOCAL_MODE else "REACHY (robot hardware)"
    print("\n" + "=" * 50)
    print(f"Voice Conversation Loop  [{mode}]")
    print("STT: Whisper base.en (local)")
    print("LLM: Claude (streaming)")
    print("TTS: ElevenLabs (streaming)")
    print("=" * 50)
    print("\nPress Ctrl+C to exit.\n")

    global _reachy_mini
    if LOCAL_MODE:
        conversation_loop()
    else:
        with ReachyMini() as mini:
            _reachy_mini = mini
            print("Connected to Reachy Mini!")
            conversation_loop(mini=mini)


if __name__ == "__main__":
    main()
