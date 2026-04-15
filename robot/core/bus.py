"""Bus: the one communication primitive. Publishers put, subscribers each get a copy."""

from queue import Queue


class Bus:
    def __init__(self):
        self._subscribers: list[Queue] = []

    def subscribe(self) -> Queue:
        """Get a personal inbox. Every put() delivers a copy here."""
        q = Queue()
        self._subscribers.append(q)
        return q

    def put(self, item):
        """Send to all subscribers."""
        for q in self._subscribers:
            q.put(item)
