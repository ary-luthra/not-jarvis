"""DTLN-aec test: neural network echo cancellation.

Plays TTS speech through speaker while recording mic.
DTLN-aec removes the known speaker signal from mic input.
Talk during the test to verify your voice survives.

Usage: python robot/test_aec.py
"""

import numpy as np
import sounddevice as sd
import time
import wave
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ai_edge_litert.interpreter import Interpreter

SAMPLE_RATE = 16000
DURATION = 15
MODEL_PREFIX = "/tmp/dtln-aec/pretrained_models/dtln_aec_256"
BLOCK_LEN = 512
BLOCK_SHIFT = 128


class DTLNAec:
    """Real-time DTLN-aec echo canceller using TFLite."""

    def __init__(self, model_prefix=MODEL_PREFIX):
        self.block_len = BLOCK_LEN
        self.block_shift = BLOCK_SHIFT

        self.interpreter_1 = Interpreter(model_path=f"{model_prefix}_1.tflite")
        self.interpreter_1.allocate_tensors()
        self.interpreter_2 = Interpreter(model_path=f"{model_prefix}_2.tflite")
        self.interpreter_2.allocate_tensors()

        self.input_details_1 = self.interpreter_1.get_input_details()
        self.output_details_1 = self.interpreter_1.get_output_details()
        self.input_details_2 = self.interpreter_2.get_input_details()
        self.output_details_2 = self.interpreter_2.get_output_details()

        self.states_1 = np.zeros(self.input_details_1[1]["shape"]).astype("float32")
        self.states_2 = np.zeros(self.input_details_2[1]["shape"]).astype("float32")

        self.in_buffer = np.zeros(self.block_len).astype("float32")
        self.in_buffer_lpb = np.zeros(self.block_len).astype("float32")
        self.out_buffer = np.zeros(self.block_len).astype("float32")

    def process_block(self, mic_block, ref_block):
        """Process one block_shift-sized chunk. Returns cleaned audio of same size."""
        # Shift buffers
        self.in_buffer[: -self.block_shift] = self.in_buffer[self.block_shift :]
        self.in_buffer[-self.block_shift :] = mic_block

        self.in_buffer_lpb[: -self.block_shift] = self.in_buffer_lpb[self.block_shift :]
        self.in_buffer_lpb[-self.block_shift :] = ref_block

        # FFT of mic
        in_block_fft = np.fft.rfft(self.in_buffer).astype("complex64")
        in_mag = np.abs(in_block_fft).reshape(1, 1, -1).astype("float32")

        # FFT of reference
        lpb_block_fft = np.fft.rfft(self.in_buffer_lpb).astype("complex64")
        lpb_mag = np.abs(lpb_block_fft).reshape(1, 1, -1).astype("float32")

        # Model 1: frequency domain masking
        self.interpreter_1.set_tensor(self.input_details_1[0]["index"], in_mag)
        self.interpreter_1.set_tensor(self.input_details_1[2]["index"], lpb_mag)
        self.interpreter_1.set_tensor(self.input_details_1[1]["index"], self.states_1)
        self.interpreter_1.invoke()

        out_mask = self.interpreter_1.get_tensor(self.output_details_1[0]["index"])
        self.states_1 = self.interpreter_1.get_tensor(self.output_details_1[1]["index"])

        # Apply mask and IFFT
        estimated_block = np.fft.irfft(in_block_fft * out_mask)
        estimated_block = estimated_block.reshape(1, 1, -1).astype("float32")
        in_lpb = self.in_buffer_lpb.reshape(1, 1, -1).astype("float32")

        # Model 2: time domain enhancement
        self.interpreter_2.set_tensor(self.input_details_2[0]["index"], estimated_block)
        self.interpreter_2.set_tensor(self.input_details_2[2]["index"], in_lpb)
        self.interpreter_2.set_tensor(self.input_details_2[1]["index"], self.states_2)
        self.interpreter_2.invoke()

        out_block = self.interpreter_2.get_tensor(self.output_details_2[0]["index"])
        self.states_2 = self.interpreter_2.get_tensor(self.output_details_2[1]["index"])

        # Overlap-add
        self.out_buffer[: -self.block_shift] = self.out_buffer[self.block_shift :]
        self.out_buffer[-self.block_shift :] = 0
        self.out_buffer += np.squeeze(out_block)

        return self.out_buffer[: self.block_shift].copy()


# Generate TTS reference audio
print("Generating TTS reference audio...")
from openai import OpenAI

tts_client = OpenAI()
tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
with tts_client.audio.speech.with_streaming_response.create(
    model="tts-1",
    voice="nova",
    input=(
        "Here's a test of neural echo cancellation. I'm going to keep talking "
        "for a while so you can test if this works properly. The quick brown fox "
        "jumps over the lazy dog. Testing one two three four five. This speech "
        "should be completely removed from the recording while any real human "
        "voice is preserved. Let me keep going a bit more to give you enough time "
        "to test. How does this sound? Can you hear me clearly? I hope the echo "
        "cancellation is working well. Almost done now, just a few more seconds."
    ),
    response_format="wav",
) as response:
    response.stream_to_file(tmp.name)

# Load and convert
import scipy.io.wavfile as wavfile
from scipy.signal import resample

orig_rate, wav_data = wavfile.read(tmp.name)
if wav_data.ndim > 1:
    wav_data = wav_data[:, 0]
wav_float = wav_data.astype(np.float32) / np.iinfo(wav_data.dtype).max
if orig_rate != SAMPLE_RATE:
    n_samples = int(len(wav_float) * SAMPLE_RATE / orig_rate)
    wav_float = resample(wav_float, n_samples).astype(np.float32)

target_len = SAMPLE_RATE * DURATION
if len(wav_float) < target_len:
    ref_audio = np.zeros(target_len, dtype=np.float32)
    ref_audio[: len(wav_float)] = wav_float
else:
    ref_audio = wav_float[:target_len]

ref_audio *= 0.5
os.unlink(tmp.name)
print(f"Reference: {len(ref_audio)/SAMPLE_RATE:.1f}s of TTS speech")

# Load DTLN-aec
print("Loading DTLN-aec model...")
ec = DTLNAec()
print("Model loaded!")

# Real-time processing
raw_rec = []
clean_rec = []
pos = [0]
mic_buffer = np.zeros(0, dtype=np.float32)
ref_buffer = np.zeros(0, dtype=np.float32)


def callback(indata, outdata, frames, time_info, status):
    global mic_buffer, ref_buffer

    mic = indata[:, 0].copy()

    # Speaker output
    s = pos[0]
    e = min(s + frames, len(ref_audio))
    spk = np.zeros(frames, np.float32)
    if s < len(ref_audio):
        spk[: e - s] = ref_audio[s:e]
        pos[0] = e
    outdata[:, 0] = spk

    # Accumulate buffers
    mic_buffer = np.concatenate([mic_buffer, mic])
    ref_buffer = np.concatenate([ref_buffer, spk])

    # Process in BLOCK_SHIFT-sized chunks
    while len(mic_buffer) >= BLOCK_SHIFT and len(ref_buffer) >= BLOCK_SHIFT:
        mic_chunk = mic_buffer[:BLOCK_SHIFT]
        ref_chunk = ref_buffer[:BLOCK_SHIFT]
        mic_buffer = mic_buffer[BLOCK_SHIFT:]
        ref_buffer = ref_buffer[BLOCK_SHIFT:]

        clean_chunk = ec.process_block(mic_chunk, ref_chunk)
        clean_rec.append(clean_chunk)

    raw_rec.append(mic)


print(f"\nPlaying TTS + recording for {DURATION}s...")
print(">>> SPEAK NOW to test if your voice survives <<<\n")

with sd.Stream(
    samplerate=SAMPLE_RATE, channels=1, dtype="float32",
    blocksize=1024, callback=callback,
):
    time.sleep(DURATION)

raw = np.concatenate(raw_rec)
clean = np.concatenate(clean_rec)

rr = np.sqrt(np.mean(raw**2))
cr = np.sqrt(np.mean(clean**2))
print(f"\nRaw mic RMS:   {rr:.4f}")
print(f"Clean mic RMS: {cr:.4f}")
if rr > 1e-10:
    print(f"Reduction:     {20 * np.log10(cr / rr):.1f} dB")

for name, data in [("raw_mic.wav", raw), ("clean_mic.wav", clean)]:
    with wave.open(name, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes((data * 32767).astype(np.int16).tobytes())
    print(f"Saved {name}")

print("\nListen to both — TTS should be removed, your voice should remain.")
