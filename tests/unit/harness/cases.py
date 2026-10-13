"""Synthetic prompt and harness boundary records."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lgcw.models.handoff import BuildHandoff
from lgcw.models.issue import IssueSnapshot
from lgcw.models.review import CodeLocation, GatedFinding, LineRange, ReviewFinding


def issue(body: str = "## Acceptance criteria\n- release 0.1.1") -> IssueSnapshot:
    """Return a bounded version-bump fixture."""
    return IssueSnapshot(
        repo="fixture/sandbox",
        number=7,
        title="Bump version",
        body=body,
        author="owner",
        state="open",
        labels=(),
        updated_at=datetime(2026, 10, 13, tzinfo=UTC),
        url="https://example.test/issues/7",
    )


def handoff() -> BuildHandoff:
    """Return complete builder claims with recognizable excluded self-assessment."""
    return BuildHandoff(
        status="done",
        summary=["UNTRUSTED_BUILDER_GRADE"],
        approach="one-file change",
        decisions=[],
        assumptions=["canonical VERSION"],
        acceptance=[],
        files=[],
        tests=[],
        not_done=[],
        risks=[],
        open_questions=[],
        followups=[],
        dispositions=[],
    )


def finding(root: Path, key: str = "F-1") -> GatedFinding:
    """Return an admitted finding for a fix or verification prompt."""
    return GatedFinding(
        id=key,
        lens="general",
        path="app.py",
        blocking=True,
        reason="introduced",
        finding=ReviewFinding(
            title="[P1] Preserve CLI version",
            body="CLI reports the old version.",
            confidence_score=0.9,
            priority=1,
            category="correctness",
            code_location=CodeLocation(
                absolute_file_path=str(root / "app.py"), line_range=LineRange(start=2, end=2)
            ),
        ),
    )
