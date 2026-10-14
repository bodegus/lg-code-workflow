"""Owner-login SDK qualification, explicitly opt-in and never in CI."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest
from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox
from openai_codex.generated.v2_all import (
    CustomToolCallOutputResponseItem,
    CustomToolCallResponseItem,
    InputTextFunctionCallOutputContentItem,
)
from pydantic import ValidationError

from lgcw.config import load_config
from lgcw.harness.codex import CodexHarness, rollout_path
from lgcw.harness.errors import HarnessError, HarnessSessionLostError
from lgcw.models.base import Strict
from lgcw.models.harness import SessionSpec, TurnInput


class SmokeOutput(Strict):
    """Two-field strict output proves schema use on first and resumed turns."""

    answer: str
    ok: bool


class ShellReceipt(Strict):
    """Pinned runtime shell receipt, independent of the model's description of a denial."""

    chunk_id: str
    wall_time_seconds: float
    exit_code: int
    original_token_count: int
    output: str


def tool_receipts(path: Path, needle: str) -> tuple[list[str], list[ShellReceipt]]:
    """Join actual custom tool calls to same-ID output receipts in this own-session rollout."""
    calls: dict[str, str] = {}
    receipts: list[ShellReceipt] = []
    for line in path.read_text().splitlines():
        record = json.loads(line)
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload", {})
        if payload.get("type") == "custom_tool_call":
            call = CustomToolCallResponseItem.model_validate(payload)
            if needle in call.input:
                calls[call.call_id] = call.input
        elif payload.get("type") == "custom_tool_call_output":
            result = CustomToolCallOutputResponseItem.model_validate(payload)
            if result.call_id not in calls or isinstance(result.output.root, str):
                continue
            for item in result.output.root:
                if isinstance(item.root, InputTextFunctionCallOutputContentItem):
                    try:
                        receipts.append(ShellReceipt.model_validate_json(item.root.text))
                    except ValidationError:
                        continue  # framing prose is not a shell execution receipt
    return list(calls.values()), receipts


@pytest.mark.live
async def test_restart_workspace_identity(tmp_path: Path) -> None:
    """Prove the resumed writable path matches the trusted temporary worktree."""
    config = load_config(Path(__file__).parents[2], home=Path.home() / ".lgcw")
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    subprocess.run(("git", "init", "-q", str(root)), check=True, timeout=5)
    skill = tmp_path / "probe" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text(
        "---\nname: probe\ndescription: Workspace identity qualification.\n---\n"
        "Perform only the tiny requested operation and report its actual result.\n"
    )
    spec = SessionSpec(
        role="builder",
        cwd=root,
        sandbox="workspace_write",
        network=True,
        effort="low",
        model=config.model,
    )

    def turn(text: str) -> TurnInput:
        return TurnInput(skill=str(skill), text=text, data=None, data_label=None)

    first = CodexHarness(config, worktree=root)
    try:
        session = await first.start_session(spec)
        await first.run_turn(
            session,
            turn("No tools. Return answer=first and ok=true."),
            SmokeOutput,
            heartbeat=lambda: None,
        )
    finally:
        await first.close()
    resumed = CodexHarness(config, worktree=root)
    try:
        result = await resumed.run_turn(
            session,
            turn(
                "Use shell once: printf resumed > resume-proof.txt. Then return answer=resumed "
                "and ok=true. No other operation."
            ),
            SmokeOutput,
            heartbeat=lambda: None,
        )
        assert result.output == SmokeOutput(answer="resumed", ok=True)
        assert (root / "resume-proof.txt").read_text() == "resumed"
        assert result.rollout_path is not None
        contexts = [
            record["payload"]
            for line in result.rollout_path.read_text().splitlines()
            if (record := json.loads(line)).get("type") == "turn_context"
        ]
        context = contexts[-1]
        assert context["cwd"] == str(root)
        entries = context["file_system_sandbox_policy"]["entries"]
        explicit_writes = {
            entry["path"]["path"]
            for entry in entries
            if entry["access"] == "write" and entry["path"]["type"] == "path"
        }
        assert explicit_writes == {str(root)}
        print(f"cross_server_resume=True cwd={context['cwd']}")
        print(f"explicit_workspace_writes={sorted(explicit_writes)} resumed_write=True")
    finally:
        await resumed.close()


@pytest.mark.live
async def test_codex_smoke(tmp_path: Path) -> None:
    config = load_config(Path(__file__).parents[2], home=Path.home() / ".lgcw")
    assert (config.codex_home / "auth.json").is_file(), "dedicated owner-created login required"
    root = tmp_path / "workspace"
    root.mkdir()
    subprocess.run(("git", "init", "-q", str(root)), check=True, timeout=5)
    (root / "AGENTS.md").write_text(
        "Repository instruction_value is cedar. Use it when asked for instruction_value.\n"
    )
    servers: list[tuple[AsyncCodex, Path]] = []

    def factory(built: CodexConfig) -> AsyncCodex:
        assert built.launch_args_override is not None
        pidfile = tmp_path / f"runtime-{len(servers)}.pid"
        script = 'pidfile=$1; shift; printf "%s\\n" "$$" > "$pidfile"; exec "$@"'
        args = ("/bin/sh", "-c", script, "lgcw-smoke", str(pidfile), *built.launch_args_override)
        sdk = AsyncCodex(replace(built, launch_args_override=args))
        servers.append((sdk, pidfile))
        return sdk

    async def assert_exited(pidfile: Path) -> None:
        assert pidfile.is_file()
        pid = int(pidfile.read_text())
        async with asyncio.timeout(3):
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return
                await asyncio.sleep(0.05)

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

    harness = CodexHarness(config, sdk_factory=factory)
    try:
        session = await harness.start_session(spec)
        unused = await harness.start_session(spec)
        first = await harness.run_turn(
            session,
            turn(
                "No tools. Remember needle=violet. Return answer equal to instruction_value "
                "from repository instructions and ok=true."
            ),
            SmokeOutput,
            heartbeat=heartbeat,
        )
        assert first.output == SmokeOutput(answer="cedar", ok=True)
        assert first.usage.input_tokens > 0 and first.usage.cached_input_tokens >= 0
        assert first.usage.context_input_tokens is not None
        assert first.rollout_path is not None and first.rollout_path.is_file()
        assert heartbeats
        duplicate = CodexHarness(config, sdk_factory=factory)
        try:
            with pytest.raises(HarnessError, match="already has"):
                await duplicate.start_session(spec)
        finally:
            await duplicate.close()
    finally:
        await harness.close()
        await assert_exited(servers[0][1])

    resumed = CodexHarness(config, sdk_factory=factory, worktree=root)
    _, resumed_pid = servers[-1]
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
        assert denied.rollout_path is not None
        calls, receipts = tool_receipts(denied.rollout_path, "denied.txt")
        assert calls and any(
            receipt.exit_code != 0
            and any(word in receipt.output.lower() for word in ("permitted", "denied", "read-only"))
            for receipt in receipts
        )
        print(f"read_only_command_observed=True exit_code={receipts[-1].exit_code}")
        print(f"read_only_write_denied=True usage={denied.usage.model_dump()}")
        cancel_session = await resumed.start_session(spec)
        task = asyncio.create_task(
            resumed.run_turn(
                cancel_session,
                turn(
                    "Use shell to run `printf ready > started.txt; sleep 2; "
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
        command_started = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        observer = CodexHarness(config, sdk_factory=factory)
        observer_sdk, observer_pid = servers[-1]
        try:
            await observer.start_session(spec)  # initialization only; no paid turn
            interrupted = await observer_sdk.thread_resume(
                cancel_session.session_id,
                approval_mode=ApprovalMode.deny_all,
                sandbox=Sandbox.workspace_write,
                config={"sandbox_workspace_write.network_access": True},
            )
            async with asyncio.timeout(5):
                while True:
                    history = await interrupted.read(include_turns=True)
                    if history.thread.turns[-1].status.value == "interrupted":
                        break
                    await asyncio.sleep(0.05)
        finally:
            await observer.close()
            await assert_exited(observer_pid)
        path = rollout_path(config.codex_home, cancel_session.session_id)
        assert path is not None
        calls, _ = tool_receipts(path, "started.txt")
        assert any("sleep 2" in call and "delayed.txt" in call for call in calls)
        await asyncio.sleep(max(0, command_started + 2.5 - time.monotonic()))
        assert not (root / "delayed.txt").exists()
        print("cancel_terminal=interrupted delayed_file_absent_after_sleep=True")
        print("active_command_cancelled=True dedicated_home_lock=True pre_turn_session_lost=True")
    finally:
        await resumed.close()
        await assert_exited(resumed_pid)
        print("owned_servers_exited=True repository_instructions_loaded=True")
