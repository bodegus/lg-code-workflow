"""Build a pure ledger from authenticated GitHub records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from lgcw.ledger.markers import parse_markers
from lgcw.models.github import IssueComment, PrDocument, PrReview, ReviewThread
from lgcw.models.ledger import LedgerEntry, PrLedger, ReviewMarker, RunMarker


def build_ledger(
    issue_comments: Sequence[IssueComment],
    pr_comments: Sequence[IssueComment],
    threads: Sequence[ReviewThread],
    workflow_login: str,
    *,
    reviews: Sequence[PrReview] = (),
    pr_document: PrDocument | None = None,
) -> PrLedger:
    """Collect only workflow-authored marker facts and order them deterministically.

    ThreadComment has no creation timestamp in the binding model. Thread facts use UTC minimum
    as an explicit unknown-time sentinel and are ordered by their comment IDs. Never infer the
    occurrence time from this sentinel; issue/PR facts retain their authoritative timestamps.
    """
    entries = _comment_entries(issue_comments, "issue", workflow_login)
    entries.extend(_comment_entries(pr_comments, "pr", workflow_login))
    if pr_document is not None and pr_document.author == workflow_login:
        for marker in parse_markers(pr_document.body):
            if isinstance(marker, RunMarker) and marker.branch == pr_document.head_ref:
                entries.append(
                    LedgerEntry(
                        comment_id=pr_document.number,
                        created_at=pr_document.created_at,
                        where="pr_body",
                        marker=marker,
                    )
                )
    for review in reviews:
        if review.author != workflow_login:
            continue
        for marker in parse_markers(review.body):
            if (
                not isinstance(marker, ReviewMarker)
                or marker.head_sha != review.head_sha
                or marker.review_id not in {None, review.id}
            ):
                continue
            entries.append(
                LedgerEntry(
                    comment_id=review.id,
                    created_at=review.submitted_at,
                    where="review",
                    marker=marker.model_copy(update={"review_id": review.id}),
                )
            )
    for thread in threads:
        for comment in thread.comments:
            if comment.author != workflow_login:
                continue
            for marker in parse_markers(comment.body):
                entries.append(
                    LedgerEntry(
                        comment_id=comment.id,
                        created_at=datetime.min.replace(tzinfo=UTC),
                        where="thread",
                        marker=marker,
                    )
                )
    entries.sort(key=lambda entry: (entry.created_at, entry.comment_id))
    unique: list[LedgerEntry] = []
    runs: set[str] = set()
    for entry in reversed(entries):
        if isinstance(entry.marker, RunMarker):
            key = entry.marker.model_dump_json(
                exclude={"body_operation_id", "body_head_sha", "body_step"}
            )
            if key in runs:
                continue
            runs.add(key)
        unique.append(entry)
    return PrLedger(entries=tuple(reversed(unique)))


def _comment_entries(
    comments: Sequence[IssueComment], where: Literal["issue", "pr"], workflow_login: str
) -> list[LedgerEntry]:
    return [
        LedgerEntry(
            comment_id=comment.id, created_at=comment.created_at, where=where, marker=marker
        )
        for comment in comments
        if comment.author == workflow_login
        for marker in parse_markers(comment.body)
    ]
