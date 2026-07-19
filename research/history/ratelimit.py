"""
Phase 2 — Space-Track rate governor.

Space-Track's published limits (verified current, July 2026): fewer than
30 requests/minute AND fewer than 300 requests/hour. Per-minute violations
return HTTP 500; per-hour violations trigger warnings/suspension. We run
with a safety margin (default 20/min, 250/hr) and block, never error, when
the budget is exhausted — a multi-day bulk download must be boring.

Implementation: dual sliding-window log. `acquire()` sleeps until a request
slot is free in BOTH windows, then records the request. Injectable clock and
sleep for deterministic tests.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        per_minute: int = 20,
        per_hour: int = 250,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if per_minute < 1 or per_hour < 1:
            raise ValueError("rate limits must be >= 1")
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._clock = clock
        self._sleep = sleep
        self._minute_log: deque[float] = deque()
        self._hour_log: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._minute_log and now - self._minute_log[0] >= 60.0:
            self._minute_log.popleft()
        while self._hour_log and now - self._hour_log[0] >= 3600.0:
            self._hour_log.popleft()

    def _wait_needed(self, now: float) -> float:
        wait = 0.0
        if len(self._minute_log) >= self.per_minute:
            wait = max(wait, 60.0 - (now - self._minute_log[0]))
        if len(self._hour_log) >= self.per_hour:
            wait = max(wait, 3600.0 - (now - self._hour_log[0]))
        return wait

    def acquire(self) -> float:
        """Block until a request may be sent; returns seconds slept."""
        total_slept = 0.0
        while True:
            now = self._clock()
            self._prune(now)
            wait = self._wait_needed(now)
            if wait <= 0:
                self._minute_log.append(now)
                self._hour_log.append(now)
                return total_slept
            self._sleep(wait)
            total_slept += wait
