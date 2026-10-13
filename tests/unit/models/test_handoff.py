"""Agent output must include every handoff field."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lgcw.models.handoff import BuildHandoff


@pytest.mark.unit
def test_handoff_round_trip() -> None:
    handoff = BuildHandoff(
        status="done",
        summary=["Bump version"],
        approach="Bounded version change",
        decisions=[],
        assumptions=[],
        acceptance=[],
        files=[],
        tests=[],
        not_done=[],
        risks=[],
        open_questions=[],
        followups=[],
        dispositions=[],
    )
    assert BuildHandoff.model_validate_json(handoff.model_dump_json()) == handoff


@pytest.mark.unit
def test_handoff_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        BuildHandoff.model_validate({"status": "done", "summary": []})
