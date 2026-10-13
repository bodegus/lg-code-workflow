"""Mutable graph state, typed harness results, and deterministic clocks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lgcw.clock import SystemClock
from lgcw.models.harness import TurnOutcome, Usage
from lgcw.models.issue import IssueRef
from lgcw.models.review import FindingCheck
from lgcw.models.state import RunState
from tests.fakes.clock import FakeClock


@pytest.mark.unit
def test_state_is_mutable_without_shared_defaults() -> None:
    first = RunState(issue_ref=IssueRef(repo="a/b", number=1))
    second = RunState(issue_ref=IssueRef(repo="a/b", number=2))
    first.next_step = "build"
    assert second.next_step == "reconcile"
    assert first.ledger.entries == ()
    assert "counters" not in RunState.model_fields


@pytest.mark.unit
def test_generic_turn_outcome_round_trip() -> None:
    result = TurnOutcome[FindingCheck](
        session_id="synthetic",
        output=FindingCheck(valid=True, introduced_by_change=True, reason="Synthetic evidence"),
        usage=Usage(
            input_tokens=10,
            cached_input_tokens=5,
            output_tokens=3,
            reasoning_output_tokens=1,
            context_window=None,
        ),
        duration_s=0.5,
        rollout_path=None,
    )
    assert TurnOutcome[FindingCheck].model_validate_json(result.model_dump_json()) == result


@pytest.mark.unit
async def test_fake_clock_advances_without_waiting() -> None:
    start = datetime(2026, 10, 13, tzinfo=UTC)
    clock = FakeClock(start)
    await clock.sleep(2.5)
    assert clock.now() == start + timedelta(seconds=2.5)


@pytest.mark.unit
async def test_system_clock_uses_utc() -> None:
    clock = SystemClock()
    before = datetime.now(UTC)
    await clock.sleep(0)
    assert before <= clock.now() <= datetime.now(UTC)
