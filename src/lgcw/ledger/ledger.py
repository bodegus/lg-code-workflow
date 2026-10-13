"""Build a pure ledger from authenticated GitHub records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from lgcw.ledger.markers import parse_markers
from lgcw.models.github import IssueComment, ReviewThread
from lgcw.models.ledger import LedgerEntry, PrLedger


def build_ledger(
    issue_comments: Sequence[IssueComment],
    pr_comments: Sequence[IssueComment],
    threads: Sequence[ReviewThread],
    workflow_login: str,
) -> PrLedger:
    """Collect only workflow-authored marker facts and order them deterministically.

    ThreadComment has no creation timestamp in the binding model. Thread facts use UTC minimum
    as an explicit unknown-time sentinel and are ordered by their comment IDs. Never infer the
    occurrence time from this sentinel; issue/PR facts retain their authoritative timestamps.
    """
    entries = _comment_entries(issue_comments, "issue", workflow_login)
    entries.extend(_comment_entries(pr_comments, "pr", workflow_login))
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
    return PrLedger(entries=tuple(entries))


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
