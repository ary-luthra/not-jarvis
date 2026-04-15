"""Entry point: run the voice pipeline from the terminal.

Usage:
    python -m robot.main                  # text input mode
    python -m robot.main --voice          # voice input mode (TODO: phase 2)
    python -m robot.main --debug          # verbose logging
"""

import argparse
import logging
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


def main():
    parser = argparse.ArgumentParser(description="Reachy Mini voice pipeline")
    parser.add_argument("--voice", action="store_true", help="Use mic input (TODO)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 50)
    print("  Robot Voice Pipeline")
    print("=" * 50)

    with Orchestrator() as orch:
        text_loop(orch)

    print("\nGoodbye!")


if __name__ == "__main__":
    main()
