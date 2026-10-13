"""Authoritative facts, questions, per-head lookups and derived counters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lgcw.ledger.commands import owner_commands
from lgcw.ledger.ledger import build_ledger
from lgcw.ledger.markers import render_marker
from lgcw.models.github import IssueComment, PrReview, ReviewThread, ThreadComment
from lgcw.models.ledger import (
    AckMarker,
    AskMarker,
    CiMarker,
    FindingMarker,
    LedgerEntry,
    Marker,
    PrLedger,
    PushMarker,
    ReadyMarker,
    ReviewMarker,
    SessionMarker,
)


def _comment(number: int, author: str, body: str) -> IssueComment:
    return IssueComment(
        id=number,
        author=author,
        body=body,
        created_at=datetime(2026, 10, 13, tzinfo=UTC) + timedelta(seconds=number),
    )


@pytest.mark.unit
def test_no_inline_review_receipt_recovers_atomic_round_marker() -> None:
    marker = ReviewMarker(
        head_sha="a" * 40,
        level="light",
        round=1,
        lenses=("general",),
        blocking=0,
        nonblocking=0,
        review_id=None,
    )
    receipt = PrReview(
        id=42,
        author="bot",
        body=render_marker(marker),
        head_sha="a" * 40,
        submitted_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    ledger = build_ledger([], [], [], "bot", reviews=[receipt])
    entry = ledger.latest("review")
    assert entry and entry.where == "review" and entry.comment_id == 42
    assert isinstance(entry.marker, ReviewMarker) and entry.marker.review_id == 42
    assert ledger.counts().review_rounds == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "author,head,review_id",
    [("foreign", "a" * 40, None), ("bot", "b" * 40, None), ("bot", "a" * 40, 99)],
)
def test_review_receipt_must_match_authenticated_author_head_and_id(
    author: str, head: str, review_id: int | None
) -> None:
    marker = ReviewMarker(
        head_sha="a" * 40,
        level="light",
        round=1,
        lenses=("general",),
        blocking=0,
        nonblocking=0,
        review_id=review_id,
    )
    receipt = PrReview(
        id=42,
        author=author,
        body=render_marker(marker),
        head_sha=head,
        submitted_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    assert build_ledger([], [], [], "bot", reviews=[receipt]).entries == ()


def _ledger(*markers: Marker) -> PrLedger:
    return PrLedger(
        entries=tuple(
            LedgerEntry(
                comment_id=index,
                created_at=datetime(2026, 10, 13, tzinfo=UTC),
                where="pr",
                marker=marker,
            )
            for index, marker in enumerate(markers, 1)
        )
    )


@pytest.mark.unit
def test_forged_marker_and_foreign_command_ignored() -> None:
    ready = ReadyMarker(head_sha="a")
    push = PushMarker(head_sha="a", source="build", round=0)
    forged = _comment(1, "mallory", "hi " + render_marker(ready))
    ours = _comment(2, "bodegus", "ok " + render_marker(push))
    ledger = build_ledger([], [forged, ours], [], workflow_login="bodegus")
    assert [entry.comment_id for entry in ledger.entries] == [2]
    commands = owner_commands(
        [
            _comment(3, "mallory", "/lgcw abort"),
            _comment(4, "bodegus", "/lgcw abort " + render_marker(push)),
        ],
        {"bodegus"},
        after_comment_id=0,
    )
    assert commands == []


@pytest.mark.unit
def test_issue_pr_and_thread_facts_are_collected() -> None:
    marker = FindingMarker(id="synthetic", priority=1, lens="general", head_sha="a")
    thread = ReviewThread(
        node_id="thread-1",
        is_resolved=False,
        path="a.py",
        line=1,
        comments=(
            ThreadComment(id=10, author="owner", body=render_marker(marker)),
            ThreadComment(id=11, author="outsider", body=render_marker(marker)),
        ),
    )
    first = _comment(1, "owner", render_marker(AskMarker(seq=1, step="intake", code="missing")))
    last = _comment(2, "owner", render_marker(ReadyMarker(head_sha="a")))
    ledger = build_ledger([first], [last], [thread], "owner")
    assert {(entry.where, entry.comment_id) for entry in ledger.entries} == {
        ("issue", 1),
        ("pr", 2),
        ("thread", 10),
    }
    ready = ledger.latest("ready")
    assert ready is not None and ready.comment_id == 2


@pytest.mark.unit
def test_comments_are_chronological() -> None:
    first = _comment(1, "owner", render_marker(ReadyMarker(head_sha="a")))
    last = _comment(2, "owner", render_marker(ReadyMarker(head_sha="b")))
    ledger = build_ledger([], [last, first], [], "owner")
    assert [entry.comment_id for entry in ledger.of_kind("ready")] == [1, 2]
    assert ledger.latest("absent") is None


@pytest.mark.unit
def test_pending_ask_cleared_by_ack() -> None:
    ask = AskMarker(seq=1, step="build", code="missing")
    ack = AckMarker(seq=1, command_id=9, verb="answer")
    ledger = _ledger(ask, ack, AskMarker(seq=2, step="ci_wait", code="missing"))
    pending = ledger.pending_ask()
    assert pending is not None and isinstance(pending.marker, AskMarker)
    assert pending.marker.seq == 2
    assert _ledger(ask, ack).pending_ask() is None
    assert _ledger(ack, ask).pending_ask() is not None


@pytest.mark.unit
def test_head_scoped_facts_and_empty_ledger() -> None:
    first = CiMarker(
        head_sha="a", status="success", klass=None, action="proceed_note", fingerprint=None
    )
    second = first.model_copy(update={"head_sha": "b"})
    review = ReviewMarker(
        head_sha="a",
        level="light",
        round=1,
        lenses=("general",),
        blocking=0,
        nonblocking=0,
        review_id=3,
    )
    push = PushMarker(head_sha="b", source="build", round=0)
    ledger = _ledger(first, review, second, push)
    assert ledger.ci_for("a") == first
    assert ledger.ci_for("b") == second
    assert ledger.ci_for("absent") is None
    assert ledger.reviews_for("a") == [review]
    assert ledger.reviews_for("b") == []
    assert ledger.last_push() == push
    assert _ledger().last_push() is None
    assert _ledger().counts().reruns_total == 0


@pytest.mark.unit
def test_counts_derived_from_markers() -> None:
    ledger = _ledger(
        PushMarker(head_sha="a", source="initial", round=0),
        PushMarker(head_sha="b", source="build", round=0),
        CiMarker(head_sha="b", status="failure", klass="change", action="fix", fingerprint="x"),
        PushMarker(head_sha="c", source="ci_fix", round=1),
        CiMarker(head_sha="c", status="failure", klass="infra", action="rerun", fingerprint="y"),
        CiMarker(head_sha="c", status="failure", klass="infra", action="rerun", fingerprint="y"),
        PushMarker(head_sha="d", source="gate_fix", round=1),
        PushMarker(head_sha="e", source="review_fix", round=1),
        SessionMarker(role="builder", session_id="first", reason="initial"),
        SessionMarker(role="builder", session_id="second", reason="fresh_restart"),
        ReviewMarker(
            head_sha="e",
            level="light",
            round=1,
            lenses=("general",),
            blocking=0,
            nonblocking=0,
            review_id=3,
        ),
    )
    counts = ledger.counts()
    assert (counts.ci_fix_rounds, counts.reruns_by_head["c"], counts.reruns_total) == (1, 2, 2)
    assert (counts.gate_fix_rounds, counts.review_fix_rounds) == (1, 1)
    assert (counts.review_rounds, counts.fresh_restarts) == (1, 1)
