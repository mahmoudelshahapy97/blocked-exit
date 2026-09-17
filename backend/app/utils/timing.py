"""Timing helpers: rolling FPS meter, rate limiter, UTC clock."""

from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


class FpsMeter:
    """Rolling frames-per-second over the last `window` samples."""

    def __init__(self, window: int = 30) -> None:
        self._samples: deque[float] = deque(maxlen=window)
        self._last: float | None = None

    def tick(self) -> None:
        now = time.monotonic()
        if self._last is not None:
            delta = now - self._last
            if delta > 0:
                self._samples.append(delta)
        self._last = now

    @property
    def fps(self) -> float:
        if not self._samples:
            return 0.0
        mean = sum(self._samples) / len(self._samples)
        return 1.0 / mean if mean > 0 else 0.0

    def reset(self) -> None:
        self._samples.clear()
        self._last = None


class RateLimiter:
    """Blocking pacer that keeps a loop at a target interval."""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = interval_s
        self._next_at = time.monotonic()

    def wait(self) -> None:
        if self.interval_s <= 0:
            return
        now = time.monotonic()
        sleep_for = self._next_at - now
        if sleep_for > 0:
            time.sleep(sleep_for)
            self._next_at += self.interval_s
        else:
            # Fell behind: resync rather than accumulate debt.
            self._next_at = time.monotonic() + self.interval_s


class Stopwatch:
    """Context manager measuring elapsed milliseconds."""

    def __init__(self) -> None:
        self.elapsed_ms = 0.0
        self._start = 0.0

    def __enter__(self) -> Stopwatch:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0
