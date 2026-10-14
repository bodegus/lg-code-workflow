"""Execution journals reject incomplete success receipts and preserve attempt accounting."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lgcw.models.harness import Usage
from lgcw.models.ledger import BuildMarker, GateMarker, PublishMarker, PushMarker, RunMarker
from tests.unit.graph.cases import ledger
from tests.unit.harness.cases import handoff


@pytest.mark.unit
def test_build_handoff_needs_content_binding() -> None:
    with pytest.raises(ValidationError, match="fingerprint"):
        BuildMarker(
            operation_id="b1",
            parent_sha="a" * 40,
            session_id="builder",
            source="build",
            phase="complete",
            command_id=None,
            handoff=handoff(),
            usage=Usage(
                input_tokens=1,
                cached_input_tokens=0,
                output_tokens=1,
                reasoning_output_tokens=0,
                context_window=None,
            ),
            tree_fingerprint=None,
            feedback=None,
            error=None,
        )


@pytest.mark.unit
def test_failed_gate_needs_actionable_feedback() -> None:
    with pytest.raises(ValidationError, match="feedback"):
        GateMarker(
            operation_id="g1",
            build_id="b1",
            parent_sha="a" * 40,
            phase="complete",
            code=1,
            fingerprint=None,
            tree_fingerprint="tree",
            feedback=None,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "phase,head", [("intent", "b" * 40), ("committed", None), ("complete", None)]
)
def test_publish_phase_never_invents_commit_receipt(phase: str, head: str | None) -> None:
    with pytest.raises(ValidationError, match="committed head"):
        PublishMarker.model_validate(
            {
                "operation_id": "p1",
                "build_id": "b1",
                "parent_sha": "a" * 40,
                "phase": phase,
                "head_sha": head,
                "source": "build",
                "round": 1,
            }
        )


@pytest.mark.unit
def test_body_effect_requires_all_identity_fields() -> None:
    with pytest.raises(ValidationError, match="body effect"):
        RunMarker(
            issue="example/sandbox#1",
            branch="lgcw/issue-1",
            base_sha="a" * 40,
            body_operation_id="p1",
        )


@pytest.mark.unit
def test_gate_attempt_counts_survive_reentry_without_double_counting_push() -> None:
    intent = BuildMarker(
        operation_id="b1",
        parent_sha="a" * 40,
        session_id="builder",
        source="gate_fix",
        phase="intent",
        command_id=None,
        handoff=None,
        usage=None,
        tree_fingerprint=None,
        feedback=None,
        error=None,
    )
    complete = intent.model_copy(update={"phase": "complete", "error": "HarnessError"})
    facts = ledger(
        intent, intent, complete, PushMarker(head_sha="b" * 40, source="gate_fix", round=1)
    )
    assert facts.counts().gate_fix_rounds == 1
    second = intent.model_copy(update={"operation_id": "b2"})
    assert ledger(intent, complete, second).counts().gate_fix_rounds == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "count"),
    [
        ("HarnessAuthError", 1),
        ("HarnessQuotaError", 1),
        ("HarnessSessionLostError", 1),
        ("HarnessError", 2),
    ],
)
def test_only_known_unusable_attempts_are_refunded(error: str, count: int) -> None:
    first = BuildMarker(
        operation_id="refund-1",
        parent_sha="a" * 40,
        session_id="builder",
        source="gate_fix",
        phase="intent",
        command_id=None,
        handoff=None,
        usage=None,
        tree_fingerprint=None,
        feedback=None,
        error=None,
    )
    completed = first.model_copy(update={"phase": "complete", "error": error})
    second = first.model_copy(update={"operation_id": "refund-2"})
    assert ledger(first, completed, second).counts().gate_fix_rounds == count
    assert (
        ledger(first, completed, PushMarker(head_sha="b" * 40, source="gate_fix", round=1))
        .counts()
        .gate_fix_rounds
        == 1
    )
