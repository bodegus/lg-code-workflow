"""Strict reviewer outputs and deterministic review-policy records."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from lgcw.models.base import Strict

type ReviewLevel = Literal["none", "light", "standard", "deep"]
type Lens = Literal["general", "security", "tests", "ops"]


class LineRange(Strict):
    """An inclusive one-based line range."""

    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        """Reject a reversed range."""
        if self.end < self.start:
            raise ValueError("line range end precedes start")
        return self


class CodeLocation(Strict):
    """A finding location to be checked against the reviewed checkout."""

    absolute_file_path: str
    line_range: LineRange


class ReviewFinding(Strict):
    """A potential defect with priority, confidence and evidence."""

    title: str
    body: str
    confidence_score: float = Field(ge=0, le=1)
    priority: int = Field(ge=0, le=3)
    category: str
    code_location: CodeLocation


class ReviewVerdict(Strict):
    """One fresh reviewer's structured verdict."""

    findings: list[ReviewFinding]
    overall_correctness: Literal["patch is correct", "patch is incorrect"]
    overall_explanation: str
    overall_confidence_score: float = Field(ge=0, le=1)


class FindingCheck(Strict):
    """Independent verification of a potentially blocking finding."""

    valid: bool
    introduced_by_change: bool
    reason: str


class LevelDecision(Strict):
    """The selected review level, lenses, reasons and fix cap."""

    level: ReviewLevel
    lenses: tuple[Lens, ...]
    reasons: tuple[str, ...]
    fix_round_cap: int = Field(ge=0)


class FileChange(Strict):
    """Line counts for one changed path."""

    path: str
    added: int = Field(ge=0)
    deleted: int = Field(ge=0)


class DiffStat(Strict):
    """Diff statistics used to size review."""

    files: tuple[FileChange, ...]
    excluded_paths: tuple[str, ...] = ()

    @property
    def changed_lines(self) -> int:
        """Return additions plus deletions across all paths."""
        return sum(file.added + file.deleted for file in self.files)

    @property
    def paths(self) -> tuple[str, ...]:
        """Return paths in diff order."""
        return tuple(file.path for file in self.files)


class LensVerdict(Strict):
    """A structured verdict associated with its reviewer lens."""

    lens: Lens
    verdict: ReviewVerdict


class GatedFinding(Strict):
    """A finding after deterministic location and priority checks."""

    id: str
    lens: Lens
    path: str
    finding: ReviewFinding
    blocking: bool
    reason: str


class GateResult(Strict):
    """Blocking, advisory and rejected findings after policy checks."""

    blocking: tuple[GatedFinding, ...]
    nonblocking: tuple[GatedFinding, ...]
    dropped: tuple[GatedFinding, ...]
