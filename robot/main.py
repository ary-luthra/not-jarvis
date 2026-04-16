"""Entry point: run the voice pipeline from the terminal.

Usage:
    python -m robot.main                  # voice mode (default — mic → Whisper → chat)
    python -m robot.main --text           # text mode (type to chat)
    python -m robot.main --debug          # verbose logging
"""

import argparse
import logging
import signal
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

from robot.orchestrator import Orchestrator


def text_loop(orch: Orchestrator):
    """Type messages, hear them spoken."""
    print("\nType a message (or 'quit' to exit):\n")
    while True:
        try:
            text = input("You: ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() in ("quit", "exit", "q"):
            break
        if not text.strip():
            continue

        orch.send(text)

        # Wait for audio to finish before prompting again
        time.sleep(1)
        while not orch.audio_player._audio_q.empty():
            time.sleep(0.3)
        time.sleep(1)


def voice_loop(orch: Orchestrator):
    """Listener handles everything — just keep the main thread alive."""
    print("\nListening... speak to chat. Press Ctrl+C to exit.\n")
    stop = False

    def handle_sigint(sig, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_sigint)

    while not stop:
        time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="Reachy Mini voice pipeline")
    parser.add_argument("--text", action="store_true", help="Type input instead of mic")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    mode = "Text" if args.text else "Voice"
    print("=" * 50)
    print(f"  Robot Voice Pipeline [{mode} mode]")
    print("=" * 50)

    with Orchestrator(text_mode=args.text) as orch:
        if args.text:
            text_loop(orch)
        else:
            voice_loop(orch)

    print("\nGoodbye!")


if __name__ == "__main__":
    main()
