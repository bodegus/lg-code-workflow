"""Deterministic, bounded fix-or-move-on decision table."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from lgcw.ci.classify import latest_runs
from lgcw.ci.logs import failure_fingerprint
from lgcw.ci.patterns import (
    ERROR_START,
    INFRA_PATTERNS,
    NETWORK_ERROR,
    RESOURCE_PATTERNS,
    SETUP_STEP,
    TIMEOUT_ANNOTATION,
)
from lgcw.models.ci import CiAction, CiClass, CiDecision, CiHistory, CiStatus
from lgcw.models.config import Limits, RepoConfig
from lgcw.models.github import JobView, RunView


def _job_rule(
    job: JobView,
    base: Sequence[JobView],
    log: str,
    repo: RepoConfig,
    count: int,
) -> tuple[CiClass, CiAction]:
    evidence = "\n".join((*job.annotations, log))
    baseline = [other for other in base if (other.workflow, other.name) == (job.workflow, job.name)]
    if any(pattern.search(evidence) for pattern in INFRA_PATTERNS) or (
        any(SETUP_STEP.search(step) for step in job.failed_steps) and NETWORK_ERROR.search(evidence)
    ):
        return "infra", "rerun"
    if job.conclusion == "timed_out" or TIMEOUT_ANNOTATION.search(evidence):
        base_timeout = any(
            other.conclusion == "timed_out"
            or TIMEOUT_ANNOTATION.search("\n".join(other.annotations))
            for other in baseline
        )
        return "timeout", "rerun" if base_timeout else "fix"
    if any(pattern.search(evidence) for pattern in RESOURCE_PATTERNS):
        return "resources", "rerun"
    if any(test_id in evidence for test_id in repo.known_flaky):
        return "flaky", "rerun"
    if job.failed_steps and any(
        other.conclusion == "failure" and set(job.failed_steps) <= set(other.failed_steps)
        for other in baseline
    ):
        return "pre_existing", "ask" if repo.pre_existing_policy == "ask" else "proceed_note"
    if count >= 5:
        return "mass_failure", "fix"
    if any(other.conclusion == "success" for other in baseline) and any(
        word in step.casefold() for step in job.failed_steps for word in ("build", "lint", "test")
    ):
        return "change", "fix"
    if job.conclusion in {"cancelled", "skipped", "neutral", "stale", "action_required", None}:
        return "unclassified", "ask"
    return "unclassified", "fix"


def decide(
    status: CiStatus,
    failing: Sequence[JobView],
    runs: Sequence[RunView],
    base_jobs: Sequence[JobView] | None,
    history: CiHistory,
    diff_paths: Sequence[str],
    log_tails: Mapping[int, str],
    repo: RepoConfig,
    limits: Limits,
    *,
    pushed_sha: str,
) -> CiDecision:
    """Apply table rows per required failure, aggregate actions, then enforce hard caps."""

    def result(klass: CiClass | None, action: CiAction, job: JobView | None = None) -> CiDecision:
        identity = None
        if job is not None:
            text = "\n".join((*job.annotations, *log_tails.get(job.job_id, "").splitlines()))
            first = next((line for line in text.splitlines() if ERROR_START.search(line)), text)
            identity = failure_fingerprint(
                job.workflow, job.name, job.failed_steps[0] if job.failed_steps else "", first
            )
        return CiDecision(
            head_sha=pushed_sha,
            status=status,
            klass=klass,
            action=action,
            job=job,
            fingerprint=identity,
            note=f"{status}: {klass or 'checks'} → {action}",
        )

    if status in {"head_moved", "conflict", "missing", "timeout"}:
        return result(None, "ask")
    if status == "pending":
        return result(None, "wait")
    classes = history.reruns_by_class_head.get(pushed_sha, {})
    if status == "success":
        return result("flaky" if classes.get("flaky", 0) else None, "proceed_note")
    current = latest_runs(runs, pushed_sha)
    if runs and not current:
        return result("superseded", "wait")
    if any(run.conclusion == "action_required" for run in current):
        return result("awaiting_approval", "ask")
    if any(run.conclusion == "startup_failure" for run in current):
        action: CiAction = (
            "fix" if any(path.startswith(".github/workflows/") for path in diff_paths) else "ask"
        )
        if history.ci_fix_rounds >= limits.ci_fix_rounds:
            action = "ask"
        return result("startup_failure", action)
    if not failing:
        return result("unclassified", "ask")
    decisions: list[CiDecision] = []
    for job in failing:
        klass, action = _job_rule(
            job, base_jobs or (), log_tails.get(job.job_id, ""), repo, len(failing)
        )
        used = classes.get(klass, 0)
        if action == "rerun" and klass in {"infra", "resources", "flaky"} and used >= 1:
            action = "fix" if klass == "resources" else "ask"
        if action == "rerun" and (
            history.reruns_by_head.get(pushed_sha, 0) >= limits.reruns_per_head
            or history.reruns_total >= limits.reruns_per_pr
            or history.reruns_by_head.get(pushed_sha, 0) > sum(classes.values())
        ):
            action = "ask"
        if action == "fix" and history.ci_fix_rounds >= limits.ci_fix_rounds:
            action = "ask"
        decisions.append(result(klass, action, job))
    rank = {"proceed_note": 0, "wait": 1, "rerun": 2, "fix": 3, "ask": 4}
    return max(decisions, key=lambda decision: rank[decision.action])
