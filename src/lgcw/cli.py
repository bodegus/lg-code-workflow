"""Minimal local CLI; this factory is the real-adapter authority boundary."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Literal, NoReturn

from lgcw.clock import SystemClock
from lgcw.config import load_config
from lgcw.doctor import Check, doctor
from lgcw.git.workspace import GitWorkspace
from lgcw.github.client import GitHubClient
from lgcw.github.token import GhCliTokenProvider
from lgcw.graph.context import RunContext
from lgcw.graph.runner import run_issue
from lgcw.harness.codex import CodexHarness
from lgcw.models.base import Strict
from lgcw.models.config import RepoConfig, WorkflowConfig
from lgcw.models.issue import IssueRef
from lgcw.models.state import RunOutcome
from lgcw.runlog import RunLog, redact


class CliRequest(Strict):
    """Validated command-line input, before any live capability is constructed."""

    command: Literal["run", "report", "doctor"]
    root: Path
    ref: IssueRef | None
    repo: str | None


class CliParser(argparse.ArgumentParser):
    """Leave error printing to the redacting entry point."""

    def error(self, message: str) -> NoReturn:
        """Reject arguments without printing possibly sensitive input."""
        raise ValueError(message)


def parse_args(argv: Sequence[str] | None = None) -> CliRequest:
    """Parse the three supported commands without configuration or service access."""
    parser = CliParser(prog="lgcw", description="GitHub issue to merge-ready PR; never merges.")
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Workflow checkout with config/."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "report"):
        commands.add_parser(name).add_argument("target", type=IssueRef.parse)
    commands.add_parser("doctor").add_argument("--repo")
    args = parser.parse_args(argv)
    return CliRequest(
        command=args.command,
        root=args.root,
        ref=getattr(args, "target", None),
        repo=getattr(args, "repo", None),
    )


def run_directory(config: WorkflowConfig, ref: IssueRef) -> Path:
    """Return the canonical local evidence directory for a configured issue."""
    config.repo(ref.repo)
    return config.home / "runs" / f"{ref.repo.replace('/', '__')}__{ref.number}"


async def make_context(config: WorkflowConfig, ref: IssueRef) -> RunContext:
    """Construct the real capabilities only after validating the configured target."""
    repo = config.repo(ref.repo)
    clock = SystemClock()
    tokens = GhCliTokenProvider(clock=clock)
    github = GitHubClient(tokens, allow_live=True, clock=clock)
    login = await github.viewer_login()
    if login not in repo.allowed_authors:
        raise PermissionError("GitHub login is not an allowed owner for this repository.")
    return RunContext(
        config=config,
        repo=repo,
        issue_ref=ref,
        github=github,
        workspace=GitWorkspace(config.home, token_provider=tokens, allow_live=True),
        harness=CodexHarness(config, allow_live=True, worktree=run_directory(config, ref) / "repo"),
        clock=clock,
        log=RunLog(run_directory(config, ref), clock=clock),
        workflow_login=login,
        tokens=tokens,
    )


async def execute(
    request: CliRequest,
    config: WorkflowConfig,
    *,
    context_factory: Callable[[WorkflowConfig, IssueRef], Awaitable[RunContext]] = make_context,
    runner: Callable[[RunContext], Awaitable[RunOutcome]] = run_issue,
    doctor_fn: Callable[[WorkflowConfig, RepoConfig | None], list[Check]] = doctor,
) -> int:
    """Dispatch with injected contexts in tests; close the owned harness on every run exit."""
    try:
        if request.command == "doctor":
            policy = config.repo(request.repo) if request.repo is not None else None
            checks = doctor_fn(config, policy)
            for check in checks:
                print(redact(f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}"))
            return 0 if all(check.ok for check in checks) else 1
        if request.ref is None:
            raise ValueError("Issue reference is required.")
        folder = run_directory(config, request.ref)
        if request.command == "report":
            if not (folder / "events.jsonl").is_file():
                raise FileNotFoundError("No run evidence exists for this issue.")
            path = RunLog(folder).write_report()
            print(path.read_text())
            return 0
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (folder / "lgcw-run.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("waiting: this issue already has an active local run.")
                return 2
            ctx = await context_factory(config, request.ref)
            try:
                outcome = await runner(ctx)
                print(f"{outcome}; report: {ctx.log.run_dir / 'report.md'}")
                return {"merge_ready": 0, "waiting": 2, "blocked": 3, "closed": 3, "error": 1}[
                    outcome
                ]
            finally:
                await ctx.harness.close()
    except Exception as error:
        print(redact(f"error: {type(error).__name__}: {error}"), file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI with the configured checkout and documented exit codes."""
    try:
        request = parse_args(argv)
        config = load_config(request.root)
        return asyncio.run(execute(request, config))
    except SystemExit as exit_status:
        return 0 if exit_status.code == 0 else 1
    except KeyboardInterrupt:
        print("error: interrupted; rerun the same issue to reconcile.", file=sys.stderr)
        return 1
    except Exception as error:
        print(redact(f"error: {type(error).__name__}: {error}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
