"""Typed SDK failure and lifecycle modes have deterministic controller outcomes."""

from __future__ import annotations

from pathlib import Path

import pytest
from openai_codex import CodexConfig, InvalidRequestError
from openai_codex.generated.v2_all import CodexErrorInfo, CodexErrorInfoValue, TurnError, TurnStatus

from lgcw.config import load_config
from lgcw.harness.codex import CodexHarness
from lgcw.harness.errors import (
    HarnessAuthError,
    HarnessError,
    HarnessQuotaError,
    HarnessSessionLostError,
)
from lgcw.harness.records import map_turn_error
from lgcw.models.harness import SessionRef
from tests.fakes.codex import FakeCodex
from tests.unit.harness.test_codex_boundary import Answer, prompt, spec


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,kind",
    [
        (CodexErrorInfoValue.unauthorized, HarnessAuthError),
        (CodexErrorInfoValue.usage_limit_exceeded, HarnessQuotaError),
        (CodexErrorInfoValue.rate_limit_exceeded, HarnessQuotaError),
        (CodexErrorInfoValue.internal_server_error, HarnessError),
    ],
)
def test_structured_failure_code_precedes_prose(
    code: CodexErrorInfoValue, kind: type[HarnessError]
) -> None:
    error = TurnError(
        message="Prose mentions quota and authentication ghp_" + "x" * 36,
        codex_error_info=CodexErrorInfo(root=code),
    )
    mapped = map_turn_error(error)
    assert type(mapped) is kind
    assert "ghp_" not in str(mapped)


@pytest.mark.unit
@pytest.mark.parametrize(
    "mode,kind",
    [
        ("failed", HarnessAuthError),
        ("interrupted", HarnessError),
        ("missing_usage", HarnessError),
    ],
)
async def test_terminal_failures_never_redeliver(
    tmp_path: Path, mode: str, kind: type[HarnessError]
) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path)
    sdk = FakeCodex(CodexConfig(), ['{"answer":"unused"}'])
    if mode == "failed":
        sdk.status = TurnStatus.failed
        sdk.turn_error = TurnError(
            message="Opaque server failure",
            codex_error_info=CodexErrorInfo(root=CodexErrorInfoValue.unauthorized),
        )
    elif mode == "interrupted":
        sdk.status = TurnStatus.interrupted
    else:
        sdk.missing_usage = True
    harness = CodexHarness(config, allow_live=True, sdk_factory=lambda _: sdk)
    try:
        session = await harness.start_session(spec(tmp_path))
        with pytest.raises(kind):
            await harness.run_turn(session, prompt(), Answer, heartbeat=lambda: None)
        assert sum(name == "turn" for name, _ in sdk.calls) == 1
    finally:
        await harness.close()


@pytest.mark.unit
async def test_resume_error_never_dispatches_and_role_mismatch_rejected(tmp_path: Path) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path)
    sdk = FakeCodex(CodexConfig(), [])
    harness = CodexHarness(config, allow_live=True, sdk_factory=lambda _: sdk)
    try:
        session = await harness.start_session(spec(tmp_path))
        wrong = SessionRef(session_id=session.session_id, role="reviewer")
        with pytest.raises(HarnessSessionLostError, match="role"):
            await harness.run_turn(wrong, prompt(), Answer, heartbeat=lambda: None)
        # A different durable ID follows resume, where the server reports missing rollout.
        sdk.resume_error = InvalidRequestError(-32600, "no rollout found")
        other = SessionRef(session_id="01a136dd-565b-7440-93b4-6acd056fc399", role="builder")
        with pytest.raises(HarnessSessionLostError):
            await harness.run_turn(other, prompt(), Answer, heartbeat=lambda: None)
        assert not any(name == "turn" for name, _ in sdk.calls)
    finally:
        await harness.close()


@pytest.mark.unit
async def test_initialization_and_close_errors_still_release_lock(tmp_path: Path) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path)
    sdk = FakeCodex(CodexConfig(), [])
    sdk.initialize_error = RuntimeError("initialization failed")
    sdk.close_error = RuntimeError("close failed")
    harness = CodexHarness(config, allow_live=True, sdk_factory=lambda _: sdk)
    replacement = CodexHarness(
        config, allow_live=True, sdk_factory=lambda built: FakeCodex(built, [])
    )
    try:
        with pytest.raises(HarnessError):
            await harness.start_session(spec(tmp_path))
        await replacement.start_session(spec(tmp_path))
    finally:
        sdk.close_error = None
        await harness.close()
        await replacement.close()
