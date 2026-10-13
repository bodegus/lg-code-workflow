"""Reconciliation decision table and conservative ownership/finding evidence."""

from __future__ import annotations

import pytest

from lgcw.graph.reconcile import ReconcileView, next_step
from lgcw.models.base import Step, Strict
from lgcw.models.ledger import (
    AckMarker,
    AskMarker,
    BlockedMarker,
    CiMarker,
    Command,
    FindingMarker,
    LedgerEntry,
    PushMarker,
    ReadyMarker,
    ReviewMarker,
)
from tests.unit.ci.cases import NOW, SHA
from tests.unit.graph.cases import ledger, snapshot, thread

PUSH = PushMarker(head_sha=SHA, source="build", round=1)
INITIAL = PushMarker(head_sha=SHA, source="initial", round=0)
CI = CiMarker(head_sha=SHA, status="success", klass=None, action="proceed_note", fingerprint=None)
REVIEW = ReviewMarker(
    head_sha=SHA,
    level="standard",
    round=1,
    lenses=("general",),
    blocking=0,
    nonblocking=0,
    review_id=1,
)
ASK = AskMarker(seq=1, step="build", code="question")
ANSWER = Command(verb="answer", text="bounded scope", comment_id=100, author="owner")
FINDING = FindingMarker(id="F1", priority=1, lens="general", head_sha=SHA)


def view(
    *markers: PushMarker
    | CiMarker
    | ReviewMarker
    | AskMarker
    | AckMarker
    | ReadyMarker
    | BlockedMarker,
) -> ReconcileView:
    """Return the same open PR with only the supplied durable facts."""
    return ReconcileView(
        issue=None, pr=snapshot(), ledger=ledger(*markers), threads=(), commands=()
    )


class Case(Strict):
    """An independent expected route for one durable state."""

    name: str
    state: ReconcileView
    expected: Step


CASES = (
    Case(name="no_pr", state=view().model_copy(update={"pr": None}), expected="intake"),
    Case(
        name="closed",
        state=view().model_copy(update={"pr": snapshot().model_copy(update={"state": "CLOSED"})}),
        expected="end",
    ),
    Case(name="blocked", state=view(BlockedMarker(reason="owner abort")), expected="end"),
    Case(name="waiting", state=view(PUSH, ASK), expected="end"),
    Case(
        name="answer",
        state=view(PUSH, ASK).model_copy(update={"commands": (ANSWER,)}),
        expected="build",
    ),
    Case(
        name="abort",
        state=view(PUSH, ASK).model_copy(
            update={"commands": (ANSWER.model_copy(update={"verb": "abort"}),)}
        ),
        expected="blocked",
    ),
    Case(name="ready", state=view(PUSH, ReadyMarker(head_sha=SHA)), expected="end"),
    Case(name="initial", state=view(INITIAL), expected="build"),
    Case(name="pushed", state=view(PUSH), expected="ci_wait"),
    Case(
        name="ci_fix",
        state=view(PUSH, CI.model_copy(update={"status": "failure", "action": "fix"})),
        expected="build",
    ),
    Case(
        name="ci_pending",
        state=view(PUSH, CI.model_copy(update={"status": "pending", "action": "wait"})),
        expected="ci_wait",
    ),
    Case(
        name="ci_rerun",
        state=view(PUSH, CI.model_copy(update={"status": "failure", "action": "rerun"})),
        expected="ci_wait",
    ),
    Case(
        name="ci_ask",
        state=view(PUSH, CI.model_copy(update={"status": "blocked", "action": "ask"})),
        expected="ask",
    ),
    Case(name="ci_green", state=view(PUSH, CI), expected="review"),
    Case(name="review_clean", state=view(PUSH, CI, REVIEW), expected="merge_ready"),
    Case(name="unowned", state=view(), expected="ask"),
)


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_next_step(case: Case) -> None:
    assert next_step(case.state).step == case.expected


@pytest.mark.unit
def test_next_step_head_moved_asks() -> None:
    state = view(PUSH).model_copy(
        update={"pr": snapshot().model_copy(update={"head_sha": "b" * 40})}
    )
    result = next_step(state)
    assert result.step == "ask" and result.ask is not None and result.ask.code == "head_moved"


@pytest.mark.unit
def test_answer_is_returned_and_acknowledged_command_not_reapplied() -> None:
    state = view(PUSH, ASK).model_copy(update={"commands": (ANSWER,)})
    assert next_step(state).command == ANSWER
    acknowledged = view(
        PUSH, ASK, AckMarker(seq=1, command_id=ANSWER.comment_id, verb="answer")
    ).model_copy(update={"commands": (ANSWER,)})
    assert next_step(acknowledged).command is None


@pytest.mark.unit
def test_open_blocking_thread_requires_authenticated_ledger_evidence() -> None:
    entries = (
        *ledger(PUSH, CI, REVIEW.model_copy(update={"blocking": 1})).entries,
        LedgerEntry(comment_id=99, created_at=NOW, where="thread", marker=FINDING),
    )
    state = view().model_copy(
        update={
            "ledger": ledger().model_copy(update={"entries": entries}),
            "threads": (thread(FINDING),),
        }
    )
    assert next_step(state).step == "build"
    assert (
        next_step(state.model_copy(update={"threads": (thread(FINDING, resolved=True),)})).step
        == "merge_ready"
    )
    missing = view(PUSH, CI, REVIEW.model_copy(update={"blocking": 1}))
    assert next_step(missing).step == "ask"


@pytest.mark.unit
def test_ready_without_owned_push_never_qualifies() -> None:
    assert next_step(view(ReadyMarker(head_sha=SHA))).step == "ask"
