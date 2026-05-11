"""Standalone hotword diagnostic — verifies openwakeword detects "hey jarvis".

Run on your laptop (no robot hardware required):
    pip install openwakeword sounddevice numpy
    python -m robot.diagnose_hotword              # default: int16 mode (recommended)
    python -m robot.diagnose_hotword --float32    # reproduce the current listener.py bug

Behavior:
  - Streams mic audio in 80ms chunks (1280 samples @ 16kHz)
  - Prints score every chunk (~12 prints/sec)
  - Prints a big "*** DETECTED ***" line when score > threshold
  - Say "hey jarvis" a few times — int16 mode should hit scores well above 0.5,
    float32 mode should stay near 0.0 (this is the bug in listener.py).

Ctrl+C to quit.
"""

import argparse
import queue
import sys
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
HOTWORD_CHUNK = 1280  # 80ms at 16kHz — openwakeword's expected frame size
HOTWORD_MODEL = "hey_jarvis"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--float32",
        action="store_true",
        help="Use float32 mic input (reproduces listener.py bug). Default is int16.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Detection threshold (default 0.8, matches listener.py).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print on detection, not every chunk.",
    )
    args = parser.parse_args()

    print("Loading openwakeword model...")
    from openwakeword.model import Model as WakeWordModel
    from openwakeword.utils import download_models
    download_models([HOTWORD_MODEL])
    model = WakeWordModel(
        wakeword_models=[HOTWORD_MODEL], inference_framework="onnx"
    )
    print(f"Model loaded. Mode: {'float32 (BUG REPRO)' if args.float32 else 'int16'}")
    print(f"Threshold: {args.threshold}")
    print('Say "hey jarvis" — Ctrl+C to quit.\n')

    audio_q: queue.Queue = queue.Queue()
    dtype = "float32" if args.float32 else "int16"

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[stream status] {status}", file=sys.stderr)
        audio_q.put(indata[:, 0].copy())

    last_print = 0.0
    max_score = 0.0

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype=dtype,
        blocksize=HOTWORD_CHUNK,
        callback=callback,
    ):
        try:
            while True:
                try:
                    chunk = audio_q.get(timeout=0.5)
                except queue.Empty:
                    continue

                # openwakeword expects int16 PCM. If we captured float32, this
                # mirrors what the buggy listener.py does (no conversion).
                score = model.predict(chunk).get(HOTWORD_MODEL, 0.0)
                max_score = max(max_score, score)

                now = time.time()
                if score > args.threshold:
                    print(
                        f"\n*** DETECTED *** score={score:.3f} "
                        f"(max so far: {max_score:.3f})"
                    )
                elif not args.quiet and now - last_print > 0.25:
                    bar = "#" * int(score * 40)
                    print(f"score={score:.3f}  max={max_score:.3f}  |{bar:<40}|", end="\r")
                    last_print = now
        except KeyboardInterrupt:
            print(f"\n\nDone. Max score observed: {max_score:.3f}")
            if max_score < 0.3 and args.float32:
                print("→ float32 mode never lit up. This is the listener.py bug.")
            elif max_score < 0.3:
                print("→ int16 mode also failed. Check mic permissions / input device.")
            else:
                print("→ Hotword detection works in this mode.")


if __name__ == "__main__":
    main()
