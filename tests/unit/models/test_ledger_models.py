"""Discriminated durable-record boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from lgcw.models.ledger import LedgerEntry, PushMarker


@pytest.mark.unit
def test_marker_union_discriminates() -> None:
    entry = LedgerEntry.model_validate(
        {
            "comment_id": 1,
            "created_at": datetime(2026, 10, 13, tzinfo=UTC),
            "where": "pr",
            "marker": {"kind": "push", "head_sha": "a" * 40, "source": "build", "round": 1},
        }
    )
    assert isinstance(entry.marker, PushMarker)


@pytest.mark.unit
@pytest.mark.parametrize(
    "marker",
    [
        {
            "kind": "run",
            "issue": "a/b#1",
            "branch": "lgcw/issue-1",
            "base_sha": "a" * 40,
            "flow_version": 1,
        },
        {"kind": "session", "role": "builder", "session_id": "synthetic", "reason": "initial"},
        {
            "kind": "ci",
            "head_sha": "a" * 40,
            "status": "success",
            "klass": None,
            "action": "proceed_note",
            "fingerprint": None,
        },
        {
            "kind": "review",
            "head_sha": "a" * 40,
            "level": "none",
            "round": 0,
            "lenses": [],
            "blocking": 0,
            "nonblocking": 0,
            "review_id": None,
        },
        {
            "kind": "finding",
            "id": "synthetic",
            "priority": 1,
            "lens": "general",
            "head_sha": "a" * 40,
        },
        {"kind": "ask", "seq": 1, "step": "build", "code": "incomplete"},
        {"kind": "ack", "seq": 1, "command_id": 2, "verb": "answer"},
        {"kind": "ready", "head_sha": "a" * 40},
        {"kind": "blocked", "reason": "owner_abort"},
    ],
)
def test_all_markers_round_trip(marker: dict[str, Any]) -> None:
    entry = LedgerEntry.model_validate(
        {
            "comment_id": 1,
            "created_at": datetime(2026, 10, 13, tzinfo=UTC),
            "where": "pr",
            "marker": marker,
        }
    )
    assert LedgerEntry.model_validate_json(entry.model_dump_json()) == entry
    assert entry.marker.kind == marker["kind"]


@pytest.mark.unit
def test_unknown_marker_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate(
            {
                "comment_id": 1,
                "created_at": datetime(2026, 10, 13, tzinfo=UTC),
                "where": "pr",
                "marker": {"kind": "merge"},
            }
        )
