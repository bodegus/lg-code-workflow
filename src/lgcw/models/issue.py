"""Issue identity, snapshots and deterministic intake results."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field

from lgcw.models.base import Strict


class IssueRef(Strict):
    """An owner/repository and positive issue number."""

    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    number: int = Field(gt=0)

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse an issue reference such as owner/repo#12.

        Raises:
            ValueError: The reference is malformed or its number is not positive.
        """
        repo, number = value.rsplit("#", 1)
        return cls(repo=repo, number=int(number))


class IssueSnapshot(Strict):
    """Issue content captured at intake."""

    repo: str
    number: int
    title: str
    body: str
    author: str
    state: str
    labels: tuple[str, ...]
    updated_at: datetime
    url: str
    is_pull_request: bool = False


class IntakeResult(Strict):
    """Acceptance criteria or the reason intake cannot continue."""

    status: Literal["ok", "incomplete", "rejected"]
    acceptance_criteria: tuple[str, ...]
    reason: str | None
