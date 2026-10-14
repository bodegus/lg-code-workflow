"""Opt-in owner-created R1: run the real CLI, kill in ci_wait, then resume to ready."""

from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from lgcw.cli import run_directory
from lgcw.config import load_config
from lgcw.github.client import GitHubClient
from lgcw.github.token import GhCliTokenProvider
from lgcw.harness.process import terminate_runtime
from lgcw.ledger.ledger import build_ledger
from lgcw.models.base import Strict
from lgcw.models.issue import IssueRef
from lgcw.models.ledger import BuildMarker, PushMarker, ReadyMarker
from lgcw.runlog import RunLog
from lgcw.runlog.log import EventRecord, TurnRecord


class Snapshot(Strict):
    """Public durable IDs and hashes of local builder receipts, without private source logs."""

    pr_number: int
    pr_url: str
    head: str
    build_intents: tuple[tuple[str, str, int | None], ...]
    pushes: tuple[tuple[str, str, int], ...]
    reviews: tuple[int, ...]
    ready: tuple[str, ...]
    builder_turns: tuple[tuple[str, str], ...]


class Interruption(Strict):
    """Retained qualification checkpoint; a retry never repeats the intentional kill."""

    issue: IssueRef
    snapshot: Snapshot
    cli_exit: int | None


def last_node(path: Path, offset: int) -> str | None:
    """Read only complete events appended by this CLI launch, never an older run's phase."""
    if not path.exists():
        return None
    with path.open("rb") as stream:
        stream.seek(offset)
        data = stream.read()
    complete = data[: data.rfind(b"\n") + 1]
    records = [EventRecord.model_validate_json(line) for line in complete.splitlines()]
    nodes = [record.node for record in records if record.kind == "node_start"]
    return nodes[-1] if nodes else None


async def snapshot(client: GitHubClient, ref: IssueRef, folder: Path) -> Snapshot:
    """Collect authoritative GitHub facts and immutable local turn-receipt hashes."""
    pr = await client.find_pr(ref.repo, f"lgcw/issue-{ref.number}")
    assert pr is not None and pr.state == "OPEN"
    issue_comments, comments, threads, reviews, document, login = await asyncio.gather(
        client.list_issue_comments(ref.repo, ref.number),
        client.list_issue_comments(ref.repo, pr.number),
        client.list_review_threads(ref.repo, pr.number),
        client.list_pr_reviews(ref.repo, pr.number),
        client.get_pr_document(ref.repo, pr.number),
        client.viewer_login(),
    )
    ledger = build_ledger(
        issue_comments, comments, threads, login, reviews=reviews, pr_document=document
    )
    turns = []
    for path in sorted((folder / "turns").glob("*.json")):
        if TurnRecord.model_validate_json(path.read_text()).role == "builder":
            turns.append((path.name, hashlib.sha256(path.read_bytes()).hexdigest()))
    return Snapshot(
        pr_number=pr.number,
        pr_url=pr.url,
        head=pr.head_sha,
        build_intents=tuple(
            (m.operation_id, m.source, m.command_id)
            for entry in ledger.entries
            if isinstance(m := entry.marker, BuildMarker) and m.phase == "intent"
        ),
        pushes=tuple(
            (m.head_sha, m.source, m.round)
            for entry in ledger.entries
            if isinstance(m := entry.marker, PushMarker)
        ),
        reviews=tuple(review.id for review in reviews if review.author == login),
        ready=tuple(
            m.head_sha for entry in ledger.entries if isinstance(m := entry.marker, ReadyMarker)
        ),
        builder_turns=tuple(turns),
    )


@pytest.mark.live
async def test_owner_created_r1_kill_and_resume() -> None:
    """Require selected R1; retain the kill receipt across owner-assisted retries."""
    selected = os.environ.get("LGCW_SMOKE_ISSUE")
    if not selected:
        pytest.skip("needs owner-created R1 issue; set LGCW_SMOKE_ISSUE=bodegus/family-calendar#N")
    ref = IssueRef.parse(selected)
    assert ref.repo == "bodegus/family-calendar"
    root = Path(__file__).parents[2]
    home = Path(os.environ.get("LGCW_SMOKE_HOME", "~/.lgcw")).expanduser().absolute()
    config = load_config(root, home=home)
    folder = run_directory(config, ref)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = RunLog(folder)
    client = GitHubClient(GhCliTokenProvider())
    env = dict(os.environ) | {"LGCW_HOME": str(home)}
    argv = (sys.executable, "-m", "lgcw.cli", "--root", str(root), "run", selected)
    pidfile = folder / f"smoke-owned-{uuid4().hex}.pid"
    process: asyncio.subprocess.Process | None = None
    intent, killed = folder / "smoke/kill-intent.json", folder / "smoke/killed.json"
    try:
        if not killed.exists():
            assert not intent.exists(), (
                "kill outcome unknown: inspect the retained intent; do not kill twice"
            )
            events = folder / "events.jsonl"
            offset = events.stat().st_size if events.exists() else 0
            process = await asyncio.create_subprocess_exec(
                *argv, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            pidfile.write_text(str(process.pid))
            deadline = time.monotonic() + config.limits.build_run_timeout_s + 1200
            while last_node(events, offset) != "ci_wait" and process.returncode is None:
                assert time.monotonic() < deadline, (
                    "CLI did not reach ci_wait in its qualification bound"
                )
                await asyncio.sleep(1)
            assert process.returncode is None, "CLI ended before ci_wait; inspect report.md"
            before = await snapshot(client, ref, folder)
            assert last_node(events, offset) == "ci_wait", (
                "CLI left ci_wait before the controlled kill"
            )
            log.artifact(
                "smoke/kill-intent.json",
                Interruption(issue=ref, snapshot=before, cli_exit=None).model_dump_json(),
            )
            await terminate_runtime(pidfile)
            output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == -signal.SIGKILL
            log.artifact("smoke/interrupted-cli.log", output.decode(errors="replace"))
            log.artifact(
                "smoke/killed.json",
                Interruption(
                    issue=ref, snapshot=before, cli_exit=process.returncode
                ).model_dump_json(),
            )
        receipt = Interruption.model_validate_json(killed.read_text())
        assert receipt.issue == ref and receipt.cli_exit == -signal.SIGKILL
        process = await asyncio.create_subprocess_exec(
            *argv, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        pidfile.write_text(str(process.pid))
        bound = (
            config.limits.ci_deadline_s
            + config.limits.build_run_timeout_s
            + config.limits.review_run_timeout_s
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=bound)
        log.artifact(f"smoke/resumed-{uuid4().hex}.log", output.decode(errors="replace"))
        assert process.returncode == 0, (
            "CLI did not reach merge_ready; inspect the retained report/question"
        )
        before, after = receipt.snapshot, await snapshot(client, ref, folder)
        assert after.pr_number == before.pr_number
        assert set(before.builder_turns) <= set(after.builder_turns)
        assert set(before.build_intents) <= set(after.build_intents)
        assert all(
            source != "build" or command is not None
            for operation, source, command in after.build_intents
            if operation not in {item[0] for item in before.build_intents}
        )
        assert len({item[0] for item in after.build_intents}) == len(after.build_intents)
        assert len(set(after.pushes)) == len(after.pushes)
        assert len(set(after.reviews)) == len(after.reviews)
        assert after.ready.count(after.head) == 1
        pr = await client.get_pr(ref.repo, after.pr_number)
        assert not pr.is_draft and "lgcw:merge-ready" in pr.labels and pr.state == "OPEN"
        runs = await client.runs_for_sha(ref.repo, after.head, pr)
        from lgcw.ci.classify import latest_runs, owned_runs

        current = latest_runs(owned_runs(runs, ref.repo, pr), after.head)
        jobs = [job for run in current for job in await client.jobs_for_run(ref.repo, run.run_id)]
        required = {(check.workflow, check.job) for check in config.repo(ref.repo).required_checks}
        assert required <= {(job.workflow, job.name) for job in jobs if job.conclusion == "success"}
        assert len(await client.open_prs_for_head(ref.repo, pr.head_ref)) == 1
        log.artifact(f"smoke/completed-{after.head}.json", after.model_dump_json())
        print("merge_ready:", after.pr_url, after.head)
        print("kill/resume receipts:", folder / "smoke")
        print("required CI:", [(job.name, job.conclusion, job.url) for job in jobs])
    finally:
        if process is not None and process.returncode is None:
            await terminate_runtime(pidfile)
            await asyncio.wait_for(process.wait(), timeout=30)
        pidfile.unlink(missing_ok=True)
