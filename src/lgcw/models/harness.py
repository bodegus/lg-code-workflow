"""Harness sessions, inputs, usage and typed outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lgcw.models.base import Strict

type Role = Literal["builder", "reviewer", "verifier"]


class SessionSpec(Strict):
    """Explicit settings for a new or resumed agent session."""

    role: Role
    cwd: Path
    sandbox: Literal["workspace_write", "read_only"]
    network: bool
    effort: str
    model: str | None


class SessionRef(Strict):
    """Durable thread identifier and its role."""

    session_id: str
    role: Role


class TurnInput(Strict):
    """Trusted instructions separated from untrusted source data."""

    skill: str
    text: str
    data: str | None
    data_label: str | None


class Usage(Strict):
    """Measured tokens for a turn, with cached tokens tracked separately."""

    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_output_tokens: int = Field(ge=0)
    context_window: int | None = Field(gt=0)


class TurnOutcome[M: BaseModel](Strict):
    """Validated output and measured metadata for one harness turn."""

    session_id: str
    output: M
    usage: Usage
    duration_s: float = Field(ge=0)
    rollout_path: Path | None
