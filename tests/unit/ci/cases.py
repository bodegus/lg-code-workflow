"""Synthetic CI policy records shared by table-driven tests."""

from __future__ import annotations

from datetime import UTC, datetime

from lgcw.models.ci import CiClass, CiHistory
from lgcw.models.config import RepoConfig, RequiredCheck
from lgcw.models.github import JobStep, JobView, PrSnapshot, RunPullRequest, RunView

NOW = datetime(2026, 10, 13, tzinfo=UTC)
SHA = "a" * 40


def pr() -> PrSnapshot:
    """Return an open fixture PR on the workflow-owned head."""
    return PrSnapshot(
        number=1,
        node_id="pr-1",
        url="https://example.test/pr/1",
        state="OPEN",
        head_ref="lgcw/issue-1",
        head_sha=SHA,
        base_ref="main",
        is_draft=True,
        mergeable="MERGEABLE",
        merge_state="CLEAN",
        labels=(),
    )


def run(
    *,
    identifier: int = 1,
    workflow: str = "CI",
    status: str = "completed",
    conclusion: str | None = "success",
    head: str = SHA,
    attempt: int = 1,
) -> RunView:
    """Return a current-head Actions run."""
    return RunView(
        run_id=identifier,
        workflow=workflow,
        event="pull_request",
        status=status,
        conclusion=conclusion,
        head_sha=head,
        run_attempt=attempt,
        created_at=NOW,
        head_branch="lgcw/issue-1",
        head_repository="example/sandbox",
        pull_requests=(100,),
        pr_associations=(RunPullRequest(number=100, base_ref="main"),),
        workflow_path=".github/workflows/ci.yml",
    )


def job(
    *,
    identifier: int = 1,
    run_id: int = 1,
    workflow: str = "CI",
    name: str = "test",
    status: str = "completed",
    conclusion: str | None = "failure",
    attempt: int = 1,
    steps: tuple[str, ...] = ("Run tests",),
    annotations: tuple[str, ...] = (),
) -> JobView:
    """Return a job with explicit failure evidence."""
    return JobView(
        job_id=identifier,
        run_id=run_id,
        workflow=workflow,
        name=name,
        status=status,
        conclusion=conclusion,
        run_attempt=attempt,
        failed_steps=steps,
        steps_observed=True,
        steps=(
            JobStep(number=1, name="Set up job", status="completed", conclusion="success"),
            *(
                JobStep(number=i + 2, name=step, status=status, conclusion=conclusion)
                for i, step in enumerate(steps)
            ),
        ),
        annotations=annotations,
        runner_name="synthetic",
        url="https://example.test/job/1",
    )


def repo(*, policy: str = "note", flaky: tuple[str, ...] = ()) -> RepoConfig:
    """Return trusted policy for the synthetic CI workflow."""
    return RepoConfig.model_validate(
        {
            "full_name": "example/sandbox",
            "default_branch": "main",
            "allowed_authors": ["owner"],
            "setup": [],
            "gate": [],
            "required_checks": [{"workflow": "CI", "job": "test"}],
            "protected_globs": [".github/workflows/**"],
            "excluded_globs": [],
            "source_globs": ["src/**"],
            "tests_globs": ["tests/**"],
            "docs_globs": ["**/*.md"],
            "risk_classes": [],
            "known_flaky": flaky,
            "pre_existing_policy": policy,
        }
    )


def history(
    *, reruns: int = 0, total: int = 0, fixes: int = 0, classes: dict[CiClass, int] | None = None
) -> CiHistory:
    """Return bounded counters with class evidence when supplied."""
    return CiHistory(
        reruns_by_head={SHA: reruns},
        reruns_total=total,
        ci_fix_rounds=fixes,
        fingerprints=(),
        reruns_by_class_head={SHA: classes or {}},
    )


def required() -> tuple[RequiredCheck, ...]:
    """Return the exact workflow/job identity."""
    return (RequiredCheck(workflow="CI", job="test"),)


def runner_job(*, annotations: tuple[str, ...] = ()) -> JobView:
    """Return a real-shaped failure in GitHub's own numbered setup phase."""
    return job(steps=("Set up job",), annotations=annotations).model_copy(
        update={
            "steps": (
                JobStep(number=1, name="Set up job", status="completed", conclusion="failure"),
                JobStep(number=2, name="Run tests", status="queued", conclusion=None),
            ),
            "annotation_paths": tuple(".github" for _ in annotations),
        }
    )
