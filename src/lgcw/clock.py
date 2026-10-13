"""Clock port and UTC host adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Time source for deterministic deadline and polling tests."""

    def now(self) -> datetime:
        """Return the current UTC instant."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait for the requested number of seconds."""
        ...


class SystemClock:
    """Host UTC clock with asynchronous sleep."""

    def now(self) -> datetime:
        """Return the current UTC instant."""
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        """Yield without blocking the event loop."""
        await asyncio.sleep(seconds)
