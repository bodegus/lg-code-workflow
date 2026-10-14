"""Durable code-produced feedback shared by state and execution markers."""

from __future__ import annotations

from typing import Literal

from lgcw.models.base import Strict


class Feedback(Strict):
    """Code-produced feedback for a subsequent builder turn."""

    source: Literal["gate", "ci", "review", "owner", "no_changes", "rebuild"]
    summary: str
    data: str | None
    fingerprint: str | None
