"""进程内、滑动窗口的聊天限流器。"""

from __future__ import annotations

import hashlib
import secrets
from collections import deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        *,
        window_seconds: float = 60,
        max_keys: int = 10_000,
        clock: Callable[[], float],
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._salt = secrets.token_bytes(16)
        self._windows: dict[bytes, deque[float]] = {}

    def allow(self, *, token: str, client_ip: str) -> bool:
        now = self._clock()
        key = hashlib.blake2b(
            f"{token}|{client_ip}".encode(), key=self._salt, digest_size=16
        ).digest()
        self._evict(now)
        window = self._windows.get(key)
        if window is None:
            if len(self._windows) >= self._max_keys:
                return False
            window = self._windows[key] = deque()
        while window and window[0] <= now - self._window:
            window.popleft()
        if len(window) >= self._limit:
            return False
        window.append(now)
        return True

    def _evict(self, now: float) -> None:
        expired = [
            key
            for key, window in self._windows.items()
            if not window or window[-1] <= now - self._window
        ]
        for key in expired:
            del self._windows[key]
