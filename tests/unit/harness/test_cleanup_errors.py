"""Cleanup diagnostics preserve cancellation/startup causes and the public error boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from openai_codex import CodexConfig

from lgcw.config import load_config
from lgcw.harness.codex import CodexHarness
from lgcw.harness.errors import HarnessAuthError, HarnessError
from tests.fakes.codex import FakeCodex
from tests.unit.harness.test_codex_boundary import Answer, prompt, spec


@pytest.mark.unit
@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
@pytest.mark.parametrize("phase", ["cancel", "close", "startup"])
async def test_cleanup_failure_preserves_original_control_flow(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, error_type: type[Exception], phase: str
) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path)
    token = "ghp_" + "x" * 36

    async def failed_cleanup(pidfile: Path) -> None:
        raise error_type("cleanup probe " + token)

    sdk = FakeCodex(CodexConfig(), ['{"answer":"unused"}'], hang=phase == "cancel")
    harness = CodexHarness(
        config, allow_live=True, sdk_factory=lambda _: sdk, runtime_cleanup=failed_cleanup
    )
    try:
        if phase == "startup":
            sdk.initialize_error = HarnessAuthError("startup credential expired")
            with pytest.raises(HarnessAuthError, match="startup credential expired"):
                await harness.start_session(spec(tmp_path))
        else:
            session = await harness.start_session(spec(tmp_path))
            if phase == "cancel":
                task = asyncio.create_task(
                    harness.run_turn(session, prompt(), Answer, heartbeat=lambda: None)
                )
                await sdk.stream_started.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert task.cancelled()
            else:
                with pytest.raises(HarnessError, match="cleanup"):
                    await harness.close()
        assert sdk.closed
        assert "cleanup probe" in caplog.text and token not in caplog.text
        replacement = CodexHarness(
            config, allow_live=True, sdk_factory=lambda built: FakeCodex(built, [])
        )
        try:
            await replacement.start_session(spec(tmp_path))
        finally:
            await replacement.close()
    finally:
        try:
            await harness.close()
        except (HarnessError, ValueError, RuntimeError):
            # Only teardown suppresses the deliberately failed port.
            pass


@pytest.mark.unit
async def test_sdk_close_failure_is_logged_redacted_harness_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path)
    sdk = FakeCodex(CodexConfig(), [])
    harness = CodexHarness(config, allow_live=True, sdk_factory=lambda _: sdk)
    try:
        await harness.start_session(spec(tmp_path))
        token = "ghp_" + "x" * 36
        sdk.close_error = RuntimeError("sdk cleanup " + token)
        with pytest.raises(HarnessError):
            await harness.close()
        assert "sdk cleanup" in caplog.text and token not in caplog.text
    finally:
        sdk.close_error = None
        await harness.close()
