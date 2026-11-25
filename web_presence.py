"""Shared presence state for one web server process."""
import threading
import time


class Presence:
    def __init__(self, timeout=25, clock=time.monotonic):
        self._timeout = timeout
        self._clock = clock
        self._last_beat = None
        self._lock = threading.Lock()

    def beat(self):
        with self._lock:
            self._last_beat = self._clock()

    def active(self):
        with self._lock:
            return self._last_beat is not None and self._clock() - self._last_beat < self._timeout
