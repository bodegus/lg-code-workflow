"""Atomic PR-body run facts authenticate their surface and deduplicate only run copies."""

from __future__ import annotations

from datetime import timedelta

import pytest

from lgcw.ledger.ledger import build_ledger
from lgcw.ledger.markers import parse_markers, render_marker
from lgcw.models.github import IssueComment, PrDocument
from lgcw.models.ledger import CiMarker, ReadyMarker, RunMarker
from tests.unit.ci.cases import NOW, SHA

RUN = RunMarker(issue="example/sandbox#1", branch="lgcw/issue-1", base_sha="b" * 40)


def document(body: str, author: str = "bot", branch: str = "lgcw/issue-1") -> PrDocument:
    """Return an independently authored body with a known authoritative creation time."""
    return PrDocument(
        number=7, author=author, body=body, created_at=NOW, head_ref=branch, head_sha=SHA
    )


def comment(number: int, body: str) -> IssueComment:
    """Return a later workflow conversation receipt."""
    return IssueComment(
        id=number, author="bot", body=body, created_at=NOW + timedelta(seconds=number)
    )


@pytest.mark.unit
def test_atomic_run_body_is_collected_without_conversation_receipt() -> None:
    ledger = build_ledger([], [], [], "bot", pr_document=document(render_marker(RUN)))
    assert len(ledger.entries) == 1
    entry = ledger.entries[0]
    assert (entry.where, entry.comment_id, entry.created_at, entry.marker) == (
        "pr_body",
        7,
        NOW,
        RUN,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "author,branch,body",
    [
        ("foreign", "lgcw/issue-1", render_marker(RUN)),
        ("bot", "other", render_marker(RUN)),
        ("bot", "lgcw/issue-1", render_marker(ReadyMarker(head_sha=SHA))),
        ("bot", "lgcw/issue-1", render_marker(RUN) + "\nordinary trailing prose"),
    ],
)
def test_body_source_rejects_foreign_or_nonrun_facts(author: str, branch: str, body: str) -> None:
    ledger = build_ledger([], [], [], "bot", pr_document=document(body, author, branch))
    assert not ledger.entries


@pytest.mark.unit
def test_identical_run_copies_dedupe_but_distinct_reruns_remain() -> None:
    ci = CiMarker(head_sha=SHA, status="failure", klass="infra", action="rerun", fingerprint="x")
    ledger = build_ledger(
        [comment(10, render_marker(RUN))],
        [
            comment(20, render_marker(RUN)),
            comment(21, render_marker(ci)),
            comment(22, render_marker(ci)),
        ],
        [],
        "bot",
        pr_document=document(render_marker(RUN)),
    )
    runs = ledger.of_kind("run")
    assert len(runs) == 1 and runs[0].comment_id == 20 and runs[0].where == "pr"
    assert len(ledger.of_kind("ci")) == ledger.counts().reruns_total == 2


@pytest.mark.unit
def test_body_effect_metadata_does_not_duplicate_canonical_run() -> None:
    bound = RUN.model_copy(
        update={"body_operation_id": "publish-op", "body_head_sha": SHA, "body_step": "publish"}
    )
    ledger = build_ledger(
        [comment(10, render_marker(RUN))], [], [], "bot", pr_document=document(render_marker(bound))
    )
    assert len(ledger.of_kind("run")) == 1
    assert parse_markers(document(render_marker(bound)).body)[0] == bound
