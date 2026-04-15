"""Base class for all pipeline components."""

import logging
import threading

logger = logging.getLogger(__name__)


class Component:
    """A pipeline component that runs in its own thread.

    Subclasses override `run()` with their main loop.
    Use `self.running` to check if the component should keep going.
    """

    def __init__(self, name: str):
        self.name = name
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run_safe, name=self.name, daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def running(self):
        return not self._stop.is_set()

    def _run_safe(self):
        try:
            self.run()
        except Exception:
            logger.exception(f"[{self.name}] crashed")

    def run(self):
        raise NotImplementedError
