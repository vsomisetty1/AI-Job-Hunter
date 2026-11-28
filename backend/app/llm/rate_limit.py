"""Client-side pacing for Claude calls.

`RateLimiter(per_minute)` spaces calls evenly (at most `per_minute` starts in
any 60 seconds, no bursts), so a batch job such as scoring a shortlist never
hits the API's rate limits or spends faster than expected. Single process:
an asyncio lock serialises waiters. The clock and sleep are injectable for
tests.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    def __init__(
        self,
        per_minute: float,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be positive")
        self.interval = 60.0 / per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_at: float | None = None
        self._lock = asyncio.Lock()
        self.waited = 0.0  # total seconds spent waiting (monitoring, tests)

    async def acquire(self) -> None:
        """Wait until the next call may start."""
        async with self._lock:
            now = self._clock()
            if self._next_at is not None and now < self._next_at:
                delay = self._next_at - now
                self.waited += delay
                await self._sleep(delay)
                now = self._next_at
            self._next_at = now + self.interval
