"""
Timed MIDI delivery, shared by the modes that need to send something later.
"""

import heapq
import threading
import time
from typing import List, Optional, Tuple


class MessageScheduler:
    """
    Fires MIDI messages at absolute times on a single background thread.

    A heap rather than one timer per message: a busy passage can have hundreds
    in flight, and threads are the one resource a Pi has least of.
    """

    def __init__(self, send):
        """
        Args:
            send: Callable taking a list of MIDI bytes, invoked at the due time.
        """
        self._send = send
        self._heap: List[Tuple[float, int, List[int]]] = []
        self._sequence = 0
        self._stopped = False
        self._condition = threading.Condition()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def schedule(self, when: float, message: List[int]) -> None:
        """Queue a message to be sent at monotonic time ``when``."""
        with self._condition:
            if self._stopped:
                return
            self._sequence += 1
            heapq.heappush(self._heap, (when, self._sequence, list(message)))
            # Wake the thread: this may be sooner than what it is waiting for
            self._condition.notify()

    def pending(self) -> int:
        """How many messages are still queued."""
        with self._condition:
            return len(self._heap)

    def _run(self) -> None:
        while True:
            message = None

            with self._condition:
                if self._stopped:
                    return

                if not self._heap:
                    self._condition.wait()
                    continue

                when, _seq, queued = self._heap[0]
                now = time.monotonic()
                if when > now:
                    self._condition.wait(when - now)
                    continue

                heapq.heappop(self._heap)
                message = queued

            # Send outside the lock so a slow write cannot block scheduling
            if message is not None:
                self._send(message)

    def stop(self) -> None:
        """Stop the thread and discard anything still queued."""
        with self._condition:
            self._stopped = True
            self._heap.clear()
            self._condition.notify_all()

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
