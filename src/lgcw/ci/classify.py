"""Qualify only current-head, latest-attempt required jobs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from lgcw.ci.patterns import TIMEOUT_ANNOTATION
from lgcw.models.ci import CiStatus
from lgcw.models.config import Limits, RequiredCheck
from lgcw.models.github import JobView, PrSnapshot, RunView


def owned_runs(runs: Sequence[RunView], repo: str, pr: PrSnapshot) -> tuple[RunView, ...]:
    """Reject same-commit executions from another event, repository, branch or PR."""
    return tuple(
        run
        for run in runs
        if run.head_repository == repo
        and run.head_branch == pr.head_ref
        and run.event in {"pull_request", "push"}
        and (run.event != "pull_request" or pr.number in run.pull_requests)
    )


def latest_runs(runs: Sequence[RunView], head_sha: str) -> tuple[RunView, ...]:
    """Select the newest run and attempt for each workflow on the owned head."""
    latest: dict[str, RunView] = {}
    for run in runs:
        if run.head_sha != head_sha:
            continue
        old = latest.get(run.workflow)
        key = (run.created_at.timestamp() if run.created_at else 0, run.run_id, run.run_attempt)
        if old is None or key > (
            old.created_at.timestamp() if old.created_at else 0,
            old.run_id,
            old.run_attempt,
        ):
            latest[run.workflow] = run
    return tuple(latest.values())


def classify(
    required: Sequence[RequiredCheck],
    runs: Sequence[RunView],
    jobs: Sequence[JobView],
    pr: PrSnapshot,
    pushed_sha: str,
    pushed_at: datetime,
    now: datetime,
    limits: Limits,
) -> tuple[CiStatus, tuple[JobView, ...]]:
    """Classify observed required checks without treating absent or skipped work as green."""
    if pr.head_sha != pushed_sha:
        return "head_moved", ()
    if pr.mergeable == "CONFLICTING" or pr.merge_state == "DIRTY":
        return "conflict", ()
    elapsed = (now - pushed_at).total_seconds()
    waiting: CiStatus = (
        "timeout"
        if elapsed >= limits.ci_deadline_s
        else "missing"
        if elapsed >= limits.ci_start_grace_s
        else "pending"
    )
    selected = latest_runs(runs, pushed_sha)
    pairs = {(check.workflow, check.job) for check in required}
    workflows = {workflow for workflow, _ in pairs}
    relevant = [run for run in selected if not pairs or run.workflow in workflows]
    identities = {(run.workflow, run.run_id, run.run_attempt) for run in relevant}
    current = [
        job
        for job in jobs
        if (job.workflow, job.run_id, job.run_attempt) in identities
        and (not pairs or (job.workflow, job.name) in pairs)
    ]
    if any(run.status != "completed" for run in relevant):
        return ("timeout" if elapsed >= limits.ci_deadline_s else "pending"), ()
    failing = tuple(
        job for job in current if job.status == "completed" and job.conclusion != "success"
    )
    if failing:
        failed = any(
            job.conclusion in {"failure", "timed_out", "startup_failure"}
            or (
                job.conclusion == "cancelled"
                and TIMEOUT_ANNOTATION.search("\n".join(job.annotations))
            )
            for job in failing
        )
        return ("failure" if failed else "blocked"), failing
    if any(run.conclusion == "startup_failure" for run in relevant):
        return "failure", ()
    if any(run.conclusion in {"action_required", "cancelled", "stale"} for run in relevant):
        return "blocked", ()
    if any(job.status != "completed" for job in current):
        return ("timeout" if elapsed >= limits.ci_deadline_s else "pending"), ()
    observed = {(job.workflow, job.name) for job in current}
    if not current or pairs - observed:
        return waiting, ()
    return "success", ()
