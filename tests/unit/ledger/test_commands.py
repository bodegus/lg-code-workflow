"""Only allowed, unmarked owner comments become commands."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lgcw.ledger.commands import owner_commands, parse_command
from lgcw.models.github import IssueComment


@pytest.mark.unit
def test_parse_command_answer_multiline() -> None:
    assert parse_command("/lgcw answer use UTC\nand ISO dates") == (
        "answer",
        "use UTC\nand ISO dates",
    )


@pytest.mark.unit
@pytest.mark.parametrize("signature", ["-builder", "-reviewer", "-owner"])
@pytest.mark.parametrize("ending", ["", "\n", "\n\n"])
def test_terminal_role_signature_is_metadata(signature: str, ending: str) -> None:
    assert parse_command(f"/lgcw answer approve\n\n{signature}{ending}") == (
        "answer",
        "approve",
    )


@pytest.mark.unit
@pytest.mark.parametrize("signature", ["-builder", "-reviewer", "-owner"])
@pytest.mark.parametrize("verb", ["retry", "abort"])
def test_signed_empty_command_payload(signature: str, verb: str) -> None:
    assert parse_command(f"/lgcw {verb}\n\n{signature}") == (verb, "")


@pytest.mark.unit
@pytest.mark.parametrize("signature", ["-builder", "-reviewer", "-owner"])
def test_signed_multiline_answer_preserves_content(signature: str) -> None:
    assert parse_command(f"/lgcw answer use UTC\nand ISO dates\n\n{signature}") == (
        "answer",
        "use UTC\nand ISO dates",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        "approve\n-builder",
        "approve\n\n-builder\n\n-owner",
        "approve\n\n-intruder",
        "approve\n\n-builder\nmore text",
        "approve\n\n> -builder",
        "approve\n\n```\n-builder\n```",
        "approve\n\nNo, do not approve.\n\n-builder",
    ],
)
def test_signature_does_not_turn_other_payload_into_approval(payload: str) -> None:
    parsed = parse_command("/lgcw answer " + payload)
    assert parsed is not None and parsed[1] != "approve"


@pytest.mark.unit
def test_signature_does_not_grant_authority_or_hide_workflow_marker() -> None:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    comments = [
        IssueComment(
            id=1, author="outsider", body="/lgcw answer approve\n\n-owner", created_at=now
        ),
        IssueComment(
            id=2,
            author="owner",
            body="/lgcw answer approve\n<!-- lgcw:v1 {broken}\n\n-builder",
            created_at=now,
        ),
        IssueComment(id=3, author="owner", body="/lgcw answer approve\n\n-builder", created_at=now),
    ]
    commands = owner_commands(comments, {"owner"}, after_comment_id=0)
    assert [(command.comment_id, command.text) for command in commands] == [(3, "approve")]


@pytest.mark.unit
@pytest.mark.parametrize("body", ["\n/lgcw retry", " /lgcw retry\n", "/lgcw retry"])
def test_retry_command(body: str) -> None:
    assert parse_command(body) == ("retry", "")


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        "",
        "Please /lgcw retry",
        "paragraph\n/lgcw retry",
        "/lgcw merge",
        "/lgcw retry-now",
        "/lgcw",
        "/lgcwanswer yes",
    ],
)
def test_non_commands_ignored(body: str) -> None:
    assert parse_command(body) is None


@pytest.mark.unit
def test_owner_command_order_and_question_boundary() -> None:
    now = datetime(2026, 10, 13, tzinfo=UTC)
    comments = [
        IssueComment(id=4, author="owner", body="/lgcw abort", created_at=now),
        IssueComment(id=1, author="owner", body="/lgcw retry", created_at=now),
        IssueComment(id=3, author="owner", body="/lgcw answer yes", created_at=now),
        IssueComment(id=5, author="outsider", body="/lgcw abort", created_at=now),
        IssueComment(
            id=6, author="owner", body="/lgcw retry\n<!-- lgcw:v1 {broken}", created_at=now
        ),
        IssueComment(id=7, author="owner", body="ordinary text", created_at=now),
    ]
    commands = owner_commands(comments, {"owner"}, after_comment_id=1)
    assert [(command.comment_id, command.verb, command.text) for command in commands] == [
        (3, "answer", "yes"),
        (4, "abort", ""),
    ]
