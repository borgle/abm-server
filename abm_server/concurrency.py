from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic


class KeyedLockPool:
    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        async with self._guard:
            lock = self._locks[key]
        async with lock:
            yield


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Record a hit and return retry-after seconds, or zero when allowed."""
        now = monotonic()
        cutoff = now - window_seconds
        async with self._guard:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(1, int(window_seconds - (now - bucket[0])) + 1)
            bucket.append(now)
            if not bucket:
                self._hits.pop(key, None)
            return 0
