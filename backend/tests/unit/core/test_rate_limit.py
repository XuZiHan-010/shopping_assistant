"""SlidingWindowRateLimiter 的滑动窗口与容量行为。"""

from __future__ import annotations

from app.core.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_allows_up_to_limit_then_blocks_within_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is False


def test_window_slides_and_allows_after_expiry() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is False

    clock.advance(61)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True


def test_different_token_ip_pairs_have_independent_buckets() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is False
    assert limiter.allow(token="t2", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="2.2.2.2") is True


def test_new_key_rejected_once_max_keys_reached() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=10, window_seconds=60, max_keys=1, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t2", client_ip="2.2.2.2") is False
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
