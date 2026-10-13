"""Typed repository policy and bounded workflow defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from lgcw.models.base import Strict
from lgcw.models.review import ReviewLevel


def _review_fix_defaults() -> dict[ReviewLevel, int]:
    return {"none": 0, "light": 1, "standard": 2, "deep": 2}


class UnknownRepoError(KeyError):
    """The requested target has no trusted repository configuration."""


class RequiredCheck(Strict):
    """A workflow/job pair, avoiding collisions between same-named jobs."""

    workflow: str
    job: str


class RiskClass(Strict):
    """A named risk and its path globs."""

    name: str
    globs: tuple[str, ...]


class ReviewThresholds(Strict):
    """Initial diff-size thresholds from the design."""

    light_max_lines: int = Field(default=99, ge=0)
    standard_max_lines: int = Field(default=499, ge=0)
    many_files: int = Field(default=8, gt=0)


class Limits(Strict):
    """Loop caps, CI deadlines, context threshold and agent timeouts."""

    gate_fix_rounds: int = Field(default=2, ge=0)
    ci_fix_rounds: int = Field(default=3, ge=0)
    reruns_per_head: int = Field(default=2, ge=0)
    reruns_per_pr: int = Field(default=5, ge=0)
    review_fix_rounds: dict[ReviewLevel, Annotated[int, Field(ge=0)]] = Field(
        default_factory=_review_fix_defaults
    )
    ci_start_grace_s: int = Field(default=600, ge=0)
    ci_deadline_s: int = Field(default=5400, gt=0)
    poll_initial_s: int = Field(default=15, gt=0)
    poll_max_s: int = Field(default=120, gt=0)
    context_restart_ratio: float = Field(default=0.6, gt=0, le=1)
    build_run_timeout_s: int = Field(default=3600, gt=0)
    build_idle_timeout_s: int = Field(default=600, gt=0)
    review_run_timeout_s: int = Field(default=1200, gt=0)
    review_idle_timeout_s: int = Field(default=300, gt=0)
    verify_run_timeout_s: int = Field(default=300, gt=0)
    verify_idle_timeout_s: int = Field(default=120, gt=0)


class RepoConfig(Strict):
    """Trusted per-repository commands and review/CI policies."""

    full_name: str
    default_branch: str
    allowed_authors: tuple[str, ...]
    setup: tuple[str, ...]
    gate: tuple[str, ...]
    required_checks: tuple[RequiredCheck, ...]
    protected_globs: tuple[str, ...]
    excluded_globs: tuple[str, ...]
    source_globs: tuple[str, ...]
    tests_globs: tuple[str, ...]
    docs_globs: tuple[str, ...]
    risk_classes: tuple[RiskClass, ...]
    known_flaky: tuple[str, ...] = ()
    pre_existing_policy: Literal["note", "ask"] = "note"


class WorkflowConfig(Strict):
    """Complete resolved workflow configuration."""

    home: Path
    codex_home: Path
    model: str | None
    builder_effort: str
    reviewer_effort: dict[ReviewLevel, str]
    verifier_effort: str
    limits: Limits
    thresholds: ReviewThresholds
    repos: dict[str, RepoConfig]

    def repo(self, full_name: str) -> RepoConfig:
        """Return a configured target, refusing repositories outside the allowlist.

        Raises:
            UnknownRepoError: No repository configuration matches the full name.
        """
        try:
            return self.repos[full_name]
        except KeyError:
            raise UnknownRepoError(full_name) from None
