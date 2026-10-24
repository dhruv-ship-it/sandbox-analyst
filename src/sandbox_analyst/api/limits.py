"""Public-safety limits: per-IP/day/global run caps, a concurrency gate, and client IP.

Hand-rolled, in-memory, single-lock -- mirrors the proven pattern in the
ZoneWise project's `app/api.py` (read-only reference; not imported from
here), extended with a concurrency reservation since this API also caps
how many runs may execute at once (see DECISIONS.md D-068/D-071).
"""

import ipaddress
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

FORWARDED_FOR_HEADER = "x-forwarded-for"


def parse_forwarded_entry(entry: str) -> str | None:
    """One `X-Forwarded-For` entry as a bare IP address, or None if it isn't one.

    Handles a plain IPv4 address, an IPv4 address with a port
    (`203.0.113.5:51234`, which Azure App Service appends), and IPv6 with
    or without brackets/port.
    """
    text = entry.strip()
    if text.startswith("["):
        host, closing, _ = text[1:].partition("]")
        if not closing:
            return None
        text = host
    elif text.count(":") == 1:
        text = text.partition(":")[0]
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def forwarded_client_ip(header: str | None) -> str | None:
    """The real client address from `X-Forwarded-For`, trusting exactly one hop.

    Read from the RIGHT: the trusted proxy (Azure's own front end) appends
    the address it received the request from as the last entry. Anything
    to the left of that is caller-suppliable and must never be trusted --
    reading the left-most entry would let a caller bypass rate limiting by
    rotating a forged header.
    """
    if not header:
        return None
    entries = [part for part in (raw.strip() for raw in header.split(",")) if part]
    if not entries:
        return None
    return parse_forwarded_entry(entries[-1])


def client_ip(request: Request, trust_proxy: bool) -> str:
    """The caller's address, for rate limiting. Unknown callers share one bucket."""
    peer = request.client.host if request.client else "unknown"
    if not trust_proxy:
        return peer
    forwarded = forwarded_client_ip(request.headers.get(FORWARDED_FOR_HEADER))
    return forwarded or peer


class RateLimiter:
    """Per-IP hour/day windows, a global daily cap, and a concurrency reservation.

    `reserve()` checks every limit and, if all pass, atomically counts the
    run against every window AND reserves a concurrency slot in the same
    locked section -- so a caller can't slip through between "allowed" and
    "counted" under concurrent requests. `release()` frees the concurrency
    slot once a run finishes (success or failure); the time-windowed
    counters are never released early, by design -- they count "runs
    started in this window," not "runs currently in flight."
    """

    def __init__(
        self,
        per_ip_hour: int,
        per_ip_day: int,
        global_day: int,
        max_concurrent: int,
    ) -> None:
        self.per_ip_hour = per_ip_hour
        self.per_ip_day = per_ip_day
        self.global_day = global_day
        self.max_concurrent = max_concurrent
        self._lock = threading.Lock()
        self._per_ip_hourly: dict[str, deque[float]] = defaultdict(deque)
        self._per_ip_daily: dict[str, deque[float]] = defaultdict(deque)
        self._global_daily: deque[float] = deque()
        self._active = 0

    @staticmethod
    def _evict(window: deque[float], now: float, span_s: float) -> None:
        while window and now - window[0] > span_s:
            window.popleft()

    def reserve(self, ip: str) -> str | None:
        """None if the run may proceed (and is now counted + reserved); else why not."""
        now = time.monotonic()
        with self._lock:
            self._evict(self._per_ip_hourly[ip], now, 3600)
            self._evict(self._per_ip_daily[ip], now, 86400)
            self._evict(self._global_daily, now, 86400)

            if self._active >= self.max_concurrent:
                return "busy, try again shortly"
            if len(self._per_ip_hourly[ip]) >= self.per_ip_hour:
                return f"rate limit: at most {self.per_ip_hour} runs/hour from one address"
            if len(self._per_ip_daily[ip]) >= self.per_ip_day:
                return f"rate limit: at most {self.per_ip_day} runs/day from one address"
            if len(self._global_daily) >= self.global_day:
                return f"this demo's daily cap of {self.global_day} runs has been reached"

            self._per_ip_hourly[ip].append(now)
            self._per_ip_daily[ip].append(now)
            self._global_daily.append(now)
            self._active += 1
            return None

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    def reset(self) -> None:
        """Forget everything. Used between tests."""
        with self._lock:
            self._per_ip_hourly.clear()
            self._per_ip_daily.clear()
            self._global_daily.clear()
            self._active = 0
