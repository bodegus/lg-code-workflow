"""CLI dispatch with injected fake contexts, no real service construction."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lgcw.cli import execute, main, parse_args, run_directory
from lgcw.graph.context import RunContext
from lgcw.models.config import WorkflowConfig
from lgcw.models.issue import IssueRef
from lgcw.models.state import RunOutcome
from lgcw.runlog import RunLog
from tests.fakes.harness import FakeHarness
from tests.unit.graph.cases import context


@pytest.mark.unit
@pytest.mark.parametrize(
    "outcome,code",
    [("merge_ready", 0), ("waiting", 2), ("blocked", 3), ("closed", 3), ("error", 1)],
)
async def test_run_exit_codes_with_fake_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], outcome: RunOutcome, code: int
) -> None:
    ctx = context(tmp_path)
    called = []

    async def factory(config: WorkflowConfig, ref: IssueRef) -> RunContext:
        assert config == ctx.config and ref == ctx.issue_ref
        called.append(ref)
        return ctx

    async def runner(actual: RunContext) -> RunOutcome:
        assert actual is ctx
        return outcome

    assert (
        await execute(
            parse_args(["run", "example/sandbox#1"]),
            ctx.config,
            context_factory=factory,
            runner=runner,
        )
        == code
    )
    assert called == [ctx.issue_ref]
    assert isinstance(ctx.harness, FakeHarness) and ctx.harness.closed
    assert outcome in capsys.readouterr().out


@pytest.mark.unit
async def test_report_does_not_construct_live_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = context(tmp_path)
    log = RunLog(run_directory(ctx.config, ctx.issue_ref), clock=ctx.clock)
    log.event("run_start", issue_ref="example/sandbox#1")
    log.event("run_end", outcome="merge_ready")

    async def forbidden(config: WorkflowConfig, ref: IssueRef) -> RunContext:
        raise AssertionError("report constructed a live adapter")

    assert (
        await execute(
            parse_args(["report", "example/sandbox#1"]), ctx.config, context_factory=forbidden
        )
        == 0
    )
    assert "merge_ready" in capsys.readouterr().out


@pytest.mark.unit
async def test_unknown_repo_fails_before_factory(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def forbidden(config: WorkflowConfig, ref: IssueRef) -> RunContext:
        raise AssertionError("unknown target reached live adapters")

    assert (
        await execute(parse_args(["run", "foreign/repo#1"]), ctx.config, context_factory=forbidden)
        == 1
    )


@pytest.mark.unit
async def test_missing_report_is_an_error(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert await execute(parse_args(["report", "example/sandbox#1"]), ctx.config) == 1


@pytest.mark.unit
async def test_cancel_closes_the_owned_harness(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def factory(config: WorkflowConfig, ref: IssueRef) -> RunContext:
        return ctx

    async def cancelled(actual: RunContext) -> RunOutcome:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await execute(
            parse_args(["run", "example/sandbox#1"]),
            ctx.config,
            context_factory=factory,
            runner=cancelled,
        )
    assert isinstance(ctx.harness, FakeHarness) and ctx.harness.closed


@pytest.mark.unit
async def test_same_issue_lock_prevents_second_dispatch(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def factory(config: WorkflowConfig, ref: IssueRef) -> RunContext:
        calls.append(ref)
        return ctx

    async def waiting(actual: RunContext) -> RunOutcome:
        started.set()
        await release.wait()
        return "waiting"

    request = parse_args(["run", "example/sandbox#1"])
    first = asyncio.create_task(
        execute(request, ctx.config, context_factory=factory, runner=waiting)
    )
    await started.wait()
    try:
        assert await execute(request, ctx.config, context_factory=factory, runner=waiting) == 2
        assert len(calls) == 1
    finally:
        release.set()
        await first


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv", [["run", "bad"], ["report", "example/sandbox#0"], ["unknown"], ["run"]]
)
def test_invalid_arguments_are_error_exit(argv: list[str]) -> None:
    assert main(argv) == 1


@pytest.mark.unit
def test_help_succeeds_without_configuration() -> None:
    assert main(["--help"]) == 0


@pytest.mark.unit
async def test_doctor_failure_returns_error_without_live_context(tmp_path: Path) -> None:
    from lgcw.doctor import Check
    from lgcw.models.config import RepoConfig

    ctx = context(tmp_path)

    def checks(config: WorkflowConfig, repo: RepoConfig | None) -> list[Check]:
        return [Check(name="tool:npm", ok=False, detail="Install the configured npm version.")]

    async def forbidden(config: WorkflowConfig, ref: IssueRef) -> RunContext:
        raise AssertionError("doctor constructed a live workflow context")

    assert (
        await execute(
            parse_args(["doctor"]), ctx.config, doctor_fn=checks, context_factory=forbidden
        )
        == 1
    )


@pytest.mark.unit
def test_argument_error_redacts_token_shaped_input(capsys: pytest.CaptureFixture[str]) -> None:
    secret = "ghp_" + "A" * 36
    assert main(["run", secret]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err and "[REDACTED]" in captured.err
