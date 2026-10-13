"""Safe harness failures for deterministic controller handling."""

from __future__ import annotations

from datetime import datetime

from lgcw.runlog import redact


class HarnessError(RuntimeError):
    """An agent operation failed; messages are safe to record."""

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


class HarnessAuthError(HarnessError):
    """The dedicated workflow login needs owner attention."""


class HarnessQuotaError(HarnessError):
    """Quota or rate limiting requires a pause until the reported reset."""

    def __init__(
        self, message: str = "agent quota exhausted", *, resets_at: datetime | None = None
    ) -> None:
        super().__init__(message)
        self.resets_at = resets_at


class HarnessOutputError(HarnessError):
    """An output did not validate against the required model."""


class HarnessSessionLostError(HarnessError):
    """A durable agent session cannot be resumed."""
