"""Entry point: run the voice pipeline from the terminal.

Usage:
    python -m robot.main                  # voice mode (default — mic → Whisper → chat)
    python -m robot.main --text           # text mode (type to chat)
    python -m robot.main --debug          # verbose logging
"""

import argparse
import logging
import os
import signal
import time
from pathlib import Path
from queue import Empty

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

from robot.core import StateChange
from robot.orchestrator import Orchestrator


def text_loop(orch: Orchestrator):
    """Type messages, hear them spoken."""
    # Subscribe to state bus to know when response finishes
    state_q = orch.state_bus.subscribe()

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

        # Wait for idle state (response finished playing)
        while True:
            try:
                event = state_q.get(timeout=0.5)
            except Empty:
                continue
            if isinstance(event, StateChange) and event.state == "idle":
                break


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
    parser.add_argument("--robot", action="store_true", help="Connect to Reachy Mini for body motion")
    parser.add_argument(
        "--user",
        default=os.environ.get("ROBOT_USER", "aryan"),
        help="Default memory user for robot conversations",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    mode = "Text" if args.text else "Voice"
    body = "+ Robot" if args.robot else ""
    print("=" * 50)
    print(f"  Robot Voice Pipeline [{mode} mode{body}]")
    print("=" * 50)

    mini = None
    if args.robot:
        from reachy_mini import ReachyMini
        mini = ReachyMini()
        mini.__enter__()
        print("Connected to Reachy Mini!")

    try:
        with Orchestrator(text_mode=args.text, mini=mini, current_user=args.user) as orch:
            if args.text:
                text_loop(orch)
            else:
                voice_loop(orch)
    finally:
        if mini:
            mini.__exit__(None, None, None)

    print("\nGoodbye!")


if __name__ == "__main__":
    main()
