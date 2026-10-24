"""Client-side request spacing, independent of any provider's own rate limits.

A real rate limit is enforced server-side; this just keeps a cooperative
client from ever sending requests faster than its configured RPM, so a
burst of calls (e.g. the agent's repair loop) doesn't immediately draw a
429. The sleep here is request pacing, not a wait-and-poll loop.
"""

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

    def wait(self) -> None:
        """Block (if needed) until it's time for the next request, then mark it started."""
        now = self._now()
        if self._last_start is not None:
            target = self._last_start + self._min_interval_s
            if now < target:
                self._sleep(target - now)
                now = target
        self._last_start = now
