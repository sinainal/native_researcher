"""Async rate limiter."""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 0.0 if requests_per_second <= 0 else 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def wait(self) -> None:
        if self.interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            sleep_for = self._next_slot - now
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
                now = time.monotonic()
            self._next_slot = max(now, self._next_slot) + self.interval
