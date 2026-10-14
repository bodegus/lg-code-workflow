"""Explicit continuation policies for every build-directed owner question."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from lgcw.models.ledger import AckMarker, AskMarker
from lgcw.models.state import RunState

type BuildRetryPolicy = Literal["resume", "fix", "fresh", "rebuild", "inspect"]
RETRY_POLICIES: Mapping[str, BuildRetryPolicy] = MappingProxyType(
    {
        "build_unknown": "resume",
        "harness_auth": "resume",
        "harness_quota": "resume",
        "harness_error": "resume",
        "harness_session_lost": "fresh",
        "builder_restart_limit": "fresh",
        "gate_fix_limit": "fix",
        "no_changes": "fix",
        "handoff_incomplete": "resume",
        "protected_path": "resume",
        "workspace_changed": "rebuild",
        "build_evidence_missing": "rebuild",
        "local_head_changed": "inspect",
        "handoff_too_large": "inspect",
        "node_error": "resume",
    }
)


def retry_ask(state: RunState) -> AskMarker | None:
    """Return only the ask bound to this invocation's acknowledged owner retry."""
    command = state.owner_command
    if command is None or command.verb != "retry":
        return None
    ack = next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, AckMarker) and entry.marker.command_id == command.comment_id
        ),
        None,
    )
    if ack is None:
        return None
    question = next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, AskMarker) and entry.marker.seq == ack.seq
        ),
        None,
    )
    return question


def retry_question(state: RunState) -> str | None:
    """Return the question code bound to the current authenticated retry."""
    question = retry_ask(state)
    return question.code if question else None
