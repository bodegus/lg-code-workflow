"""Synthetic graph contexts and authenticated ledger records."""

from __future__ import annotations

from pathlib import Path

from lgcw.git.workspace import GitWorkspace
from lgcw.graph.context import RunContext
from lgcw.ledger.markers import render_marker
from lgcw.models.config import Limits, ReviewThresholds, WorkflowConfig
from lgcw.models.github import PrSnapshot, ReviewThread, ThreadComment
from lgcw.models.issue import IssueRef
from lgcw.models.ledger import LedgerEntry, Marker, PrLedger
from lgcw.runlog import RunLog
from tests.fakes.clock import FakeClock
from tests.fakes.github import FakeGitHub
from tests.fakes.harness import FakeHarness
from tests.unit.ci.cases import NOW, pr, repo


def ledger(*markers: Marker) -> PrLedger:
    """Return an already authenticated chronological fixture ledger."""
    return PrLedger(
        entries=tuple(
            LedgerEntry(comment_id=i + 1, created_at=NOW, where="pr", marker=marker)
            for i, marker in enumerate(markers)
        )
    )


def snapshot() -> PrSnapshot:
    """Return the currently owned synthetic head."""
    return pr()


def thread(marker: Marker, *, resolved: bool = False) -> ReviewThread:
    """Return a finding thread with its marker in the original comment."""
    return ReviewThread(
        node_id="thread-1",
        is_resolved=resolved,
        path="app.py",
        line=1,
        comments=(ThreadComment(id=99, author="owner", body=render_marker(marker)),),
    )


def context(root: Path) -> RunContext:
    """Build a typed context without constructing live services."""
    policy = repo()
    config = WorkflowConfig(
        home=root,
        codex_home=root / "codex",
        model=None,
        builder_effort="high",
        reviewer_effort={"none": "low", "light": "medium", "standard": "high", "deep": "high"},
        verifier_effort="low",
        limits=Limits(),
        thresholds=ReviewThresholds(),
        repos={policy.full_name: policy},
    )
    clock = FakeClock(NOW)
    return RunContext(
        config=config,
        repo=policy,
        issue_ref=IssueRef(repo=policy.full_name, number=1),
        github=FakeGitHub(clock=clock),
        workspace=GitWorkspace(root, origin=root / "unused.git"),
        harness=FakeHarness(),
        clock=clock,
        log=RunLog(root / "evidence", clock=clock),
        workflow_login="owner",
    )
