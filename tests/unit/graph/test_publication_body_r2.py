"""Canonical view reserves room for its atomic compact receipt."""

from __future__ import annotations

import pytest

from lgcw.graph.nodes.publish import publication_body
from lgcw.ledger.markers import parse_markers
from lgcw.models.issue import IntakeResult, IssueRef
from lgcw.models.ledger import RunMarker
from lgcw.models.state import RunState
from tests.unit.graph.cases import ledger
from tests.unit.harness.cases import handoff, issue


@pytest.mark.unit
def test_body_reserve_includes_the_actual_receipt() -> None:
    frozen = issue()
    state = RunState(
        issue_ref=IssueRef(repo=frozen.repo, number=frozen.number),
        issue=frozen,
        intake=IntakeResult(status="ok", acceptance_criteria=("release 0.1.1",), reason=None),
        ledger=ledger(
            RunMarker(
                issue=f"{frozen.repo}#{frozen.number}", branch="lgcw/issue-1", base_sha="a" * 40
            )
        ),
    )
    value = handoff().model_copy(update={"summary": ["x" * 100000]})
    body = publication_body(state, value, "a" * 16, "b" * 40)
    assert len(body) <= 60000
    receipt = parse_markers(body)[-1]
    assert receipt.kind == "run" and receipt.body_head_sha == "b" * 40
    assert body.endswith("-->")


@pytest.mark.unit
@pytest.mark.parametrize("with_receipt", [False, True])
def test_handoff_clipping_measures_escaped_receipt(with_receipt: bool) -> None:
    from lgcw.graph.handoff_size import fit_handoff
    from lgcw.ledger.markers import render_marker
    from lgcw.models.harness import Usage
    from lgcw.models.ledger import BuildMarker

    value = handoff().model_copy(update={"summary": ["→" * 12000]})
    record = BuildMarker(
        operation_id="a" * 16,
        parent_sha="a" * 40,
        session_id="fixture",
        source="build",
        phase="complete",
        command_id=None,
        handoff=value,
        usage=Usage(
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
            reasoning_output_tokens=0,
            context_window=None,
        ),
        tree_fingerprint="a" * 64,
        feedback=None,
        error=None,
    )
    fitted = fit_handoff(value, receipt=record if with_receipt else None)
    assert fitted is not None
    assert len(render_marker(record.model_copy(update={"handoff": fitted}))) <= 45000
    assert fitted.files == value.files and fitted.acceptance == value.acceptance
