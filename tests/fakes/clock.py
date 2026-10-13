"""Deterministic clock without real waiting."""

from __future__ import annotations

from datetime import datetime, timedelta


class FakeClock:
    """A mutable test clock advanced only by explicit sleeps."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        """Return the current simulated instant."""
        return self._now

    async def sleep(self, seconds: float) -> None:
        """Advance simulated time without wall-clock delay."""
        self._now += timedelta(seconds=seconds)
