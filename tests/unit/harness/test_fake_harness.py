"""Scripted harness results remain independent by role and validate requested outputs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lgcw.harness.errors import (
    HarnessAuthError,
    HarnessError,
    HarnessOutputError,
    HarnessQuotaError,
    HarnessSessionLostError,
)
from lgcw.harness.port import HarnessPort
from lgcw.models.base import Strict
from lgcw.models.harness import SessionRef, SessionSpec, TurnInput, Usage
from tests.fakes.harness import FakeHarness


class Reply(Strict):
    """Small fully required output schema."""

    answer: str


class WrongReply(Strict):
    """Incompatible output for a schema failure contract."""

    wrong: str


def spec(root: Path) -> SessionSpec:
    """Return a sandboxed builder fixture."""
    return SessionSpec(
        role="builder", cwd=root, sandbox="workspace_write", network=True, effort="high", model=None
    )


def turn() -> TurnInput:
    """Return a synthetic trusted task with no external data."""
    return TurnInput(skill="fixture-skill", text="Return a reply", data=None, data_label=None)


@pytest.mark.unit
async def test_fake_harness_records_and_raises(tmp_path: Path) -> None:
    fake = FakeHarness()
    port: HarnessPort = fake
    fake.script("builder", [Reply(answer="first"), HarnessAuthError("login expired")])
    session = await port.start_session(spec(tmp_path))
    beats: list[bool] = []
    result = await port.run_turn(session, turn(), Reply, heartbeat=lambda: beats.append(True))
    assert result.output.answer == "first" and result.usage.input_tokens > 0
    assert result.session_id == session.session_id and beats
    with pytest.raises(HarnessAuthError, match="login expired"):
        await port.run_turn(session, turn(), Reply, heartbeat=lambda: None)
    assert fake.sessions == [spec(tmp_path)] and len(fake.turns) == 2
    await port.close()
    assert fake.closed


@pytest.mark.unit
async def test_fake_usage_and_fresh_role_sessions(tmp_path: Path) -> None:
    usage = Usage(
        input_tokens=700,
        cached_input_tokens=500,
        output_tokens=10,
        reasoning_output_tokens=4,
        context_window=1000,
    )
    fake = FakeHarness(usage=usage)
    fake.script("builder", [Reply(answer="builder")])
    fake.script("reviewer", [Reply(answer="reviewer")])
    builder = await fake.start_session(spec(tmp_path))
    reviewer = await fake.start_session(
        spec(tmp_path).model_copy(
            update={"role": "reviewer", "sandbox": "read_only", "network": False}
        )
    )
    assert builder.session_id != reviewer.session_id
    result = await fake.run_turn(reviewer, turn(), Reply, heartbeat=lambda: None)
    assert result.output.answer == "reviewer" and result.usage == usage


@pytest.mark.unit
async def test_fake_rejects_wrong_output_and_exhausted_script(tmp_path: Path) -> None:
    fake = FakeHarness()
    fake.script("builder", [WrongReply(wrong="value")])
    session = await fake.start_session(spec(tmp_path))
    with pytest.raises(HarnessOutputError):
        await fake.run_turn(session, turn(), Reply, heartbeat=lambda: None)
    with pytest.raises(HarnessError, match="script"):
        await fake.run_turn(session, turn(), Reply, heartbeat=lambda: None)


@pytest.mark.unit
async def test_fake_unknown_session_and_closed_harness(tmp_path: Path) -> None:
    fake = FakeHarness()
    with pytest.raises(HarnessSessionLostError):
        await fake.run_turn(
            SessionRef(session_id="missing", role="builder"), turn(), Reply, heartbeat=lambda: None
        )
    session = await fake.start_session(spec(tmp_path))
    with pytest.raises(HarnessSessionLostError):
        await fake.run_turn(
            session.model_copy(update={"role": "reviewer"}), turn(), Reply, heartbeat=lambda: None
        )
    await fake.close()
    with pytest.raises(HarnessError, match="closed"):
        await fake.start_session(spec(tmp_path))
    with pytest.raises(HarnessError, match="closed"):
        await fake.run_turn(session, turn(), Reply, heartbeat=lambda: None)


@pytest.mark.unit
def test_quota_error_carries_reset_and_errors_redact() -> None:
    reset = datetime(2026, 10, 14, tzinfo=UTC)
    error = HarnessQuotaError("quota exhausted", resets_at=reset)
    assert error.resets_at == reset
    synthetic = "ghp_" + "A" * 36
    assert synthetic not in str(HarnessAuthError(f"invalid {synthetic}"))
