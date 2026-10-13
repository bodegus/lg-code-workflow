"""The latest acknowledged answer supersedes any bootstrap-era clarification."""

from __future__ import annotations

import pytest

from lgcw.graph.nodes.reconcile import latest_owner_answer
from lgcw.models.ledger import AckMarker, Command, RunMarker


@pytest.mark.unit
@pytest.mark.parametrize(
    "initial,answers,expected",
    [
        (None, [], None),
        ("old", [], "old"),
        ("old", ["new"], "new"),
        ("old", ["first", "latest"], "latest"),
    ],
)
def test_latest_acknowledged_owner_answer(
    initial: str | None, answers: list[str], expected: str | None
) -> None:
    run = RunMarker(
        issue="example/sandbox#1", branch="lgcw/issue-1", base_sha="a" * 40, owner_answer=initial
    )
    acks = [
        AckMarker(
            seq=index + 1,
            command_id=index + 10,
            verb="answer",
            step="build",
            command_snapshot=Command(
                verb="answer", text=text, comment_id=index + 10, author="owner"
            ),
        )
        for index, text in enumerate(answers)
    ]
    assert latest_owner_answer(run, acks) == expected
