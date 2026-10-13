"""Owner-login SDK qualification, explicitly opt-in and never in CI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lgcw.config import load_config
from lgcw.harness.codex import CodexHarness
from lgcw.harness.errors import HarnessError, HarnessSessionLostError
from lgcw.models.base import Strict
from lgcw.models.harness import SessionSpec, TurnInput


class SmokeOutput(Strict):
    """Two-field strict output proves schema use on first and resumed turns."""

    answer: str
    ok: bool


@pytest.mark.live
async def test_codex_smoke(tmp_path: Path) -> None:
    config = load_config(Path(__file__).parents[2], home=Path.home() / ".lgcw")
    assert (config.codex_home / "auth.json").is_file(), "dedicated owner-created login required"
    root = tmp_path / "workspace"
    root.mkdir()
    skill = tmp_path / "probe" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text(
        "---\nname: probe\ndescription: SDK smoke test.\n---\n"
        "Follow the explicit tiny test request. Report observed results honestly.\n"
    )
    spec = SessionSpec(
        role="builder",
        cwd=root,
        sandbox="workspace_write",
        network=True,
        effort="low",
        model=config.model,
    )
    heartbeats: list[int] = []

    def heartbeat() -> None:
        heartbeats.append(1)

    def turn(text: str) -> TurnInput:
        return TurnInput(skill=str(skill), text=text, data=None, data_label=None)

    harness = CodexHarness(config)
    try:
        session = await harness.start_session(spec)
        unused = await harness.start_session(spec)
        first = await harness.run_turn(
            session,
            turn("No tools. Remember needle=violet. Return answer=violet and ok=true."),
            SmokeOutput,
            heartbeat=heartbeat,
        )
        assert first.output == SmokeOutput(answer="violet", ok=True)
        assert first.usage.input_tokens > 0 and first.usage.cached_input_tokens >= 0
        assert first.usage.context_input_tokens is not None
        assert first.rollout_path is not None and first.rollout_path.is_file()
        assert heartbeats
        duplicate = CodexHarness(config)
        try:
            with pytest.raises(HarnessError, match="already has"):
                await duplicate.start_session(spec)
        finally:
            await duplicate.close()
    finally:
        await harness.close()

    resumed = CodexHarness(config)
    try:
        with pytest.raises(HarnessSessionLostError, match="no rollout found"):
            await resumed.run_turn(
                unused,
                turn("No tools. Return ok=true and answer=unused."),
                SmokeOutput,
                heartbeat=heartbeat,
            )
        second = await resumed.run_turn(
            session,
            turn("No tools. Return the remembered needle as answer and ok=true."),
            SmokeOutput,
            heartbeat=heartbeat,
        )
        assert second.output == SmokeOutput(answer="violet", ok=True)
        assert second.usage.input_tokens > 0
        assert second.usage.cached_input_tokens >= 0
        assert second.rollout_path == first.rollout_path
        print(f"first usage={first.usage.model_dump()} duration_s={first.duration_s:.3f}")
        print(f"resumed usage={second.usage.model_dump()} duration_s={second.duration_s:.3f}")
        print(f"cross_server_resume=True session={session.session_id} heartbeats={len(heartbeats)}")
        ro = await resumed.start_session(
            spec.model_copy(update={"role": "verifier", "sandbox": "read_only", "network": False})
        )
        denied = await resumed.run_turn(
            ro,
            turn(
                "Use shell to attempt `printf denied > denied.txt` "
                "once. No escalation or retry. Return answer describing its result, ok=true."
            ),
            SmokeOutput,
            heartbeat=heartbeat,
        )
        assert denied.output.ok and not (root / "denied.txt").exists()
        print(f"read_only_write_denied=True usage={denied.usage.model_dump()}")
        cancel_session = await resumed.start_session(spec)
        task = asyncio.create_task(
            resumed.run_turn(
                cancel_session,
                turn(
                    "Use shell to run `printf ready > started.txt; sleep 30; "
                    "printf unexpected > delayed.txt`. Wait for completion."
                ),
                SmokeOutput,
                heartbeat=heartbeat,
            )
        )
        async with asyncio.timeout(45):
            while not (root / "started.txt").exists():
                if task.done():
                    await task
                    pytest.fail("turn ended without starting the requested command")
                await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not (root / "delayed.txt").exists()
        print("active_command_cancelled=True dedicated_home_lock=True pre_turn_session_lost=True")
    finally:
        await resumed.close()
