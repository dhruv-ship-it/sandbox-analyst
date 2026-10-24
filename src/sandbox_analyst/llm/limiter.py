"""Client-side request spacing, independent of any provider's own rate limits.

A real rate limit is enforced server-side; this just keeps a cooperative
client from ever sending requests faster than its configured RPM, so a
burst of calls (e.g. the agent's repair loop) doesn't immediately draw a
429. The sleep here is request pacing, not a wait-and-poll loop.

The evaluation harness (Task 3) shares ONE client -- and therefore one
limiter -- across its whole thread pool, so `wait()` must be safe to
call concurrently (D-061): a lock serializes each thread's whole
check-then-sleep-then-record sequence, which is what actually
guarantees `60 / rpm` seconds between every pair of requests globally,
not just against the thread that happened to read `_last_start` first.
"""

import threading
import time
from collections.abc import Callable


class RateLimiter:
    """Ensures at least `60 / rpm` seconds pass between the start of consecutive requests."""

    def __init__(
        self,
        rpm: float,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval_s = 60.0 / rpm
        self._sleep = sleep
        self._now = now
        self._last_start: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block (if needed) until it's time for the next request, then mark it started."""
        with self._lock:
            now = self._now()
            if self._last_start is not None:
                target = self._last_start + self._min_interval_s
                if now < target:
                    self._sleep(target - now)
                    now = target
            self._last_start = now
