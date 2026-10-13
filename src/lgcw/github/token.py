"""Read the owner's CLI credential inside plain code, never an agent prompt."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

from lgcw.clock import Clock, SystemClock
from lgcw.github.port import TokenProvider


class TokenUnavailableError(RuntimeError):
    """The CLI could not provide a usable credential."""


class GhCliTokenProvider(TokenProvider):
    """Capture the CLI token privately, with a bounded read and 50-minute cache."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock if clock is not None else SystemClock()
        self._cached: str | None = None
        self._expires_at: datetime | None = None

    def token(self) -> str:
        """Return a cached credential or capture one without exposing CLI output.

        Raises:
            TokenUnavailableError: Run gh auth login before trying again.
        """
        now = self._clock.now()
        if self._cached is not None and self._expires_at is not None and now < self._expires_at:
            return self._cached
        try:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            raise TokenUnavailableError(
                "GitHub credential unavailable; run gh auth login"
            ) from None
        value = result.stdout.strip()
        if result.returncode != 0 or not value:
            raise TokenUnavailableError("GitHub credential unavailable; run gh auth login")
        self._cached = value
        self._expires_at = now + timedelta(minutes=50)
        return value
