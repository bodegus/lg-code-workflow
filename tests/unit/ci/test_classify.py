"""Current-head/attempt qualification, missing checks and strict terminal states."""

from __future__ import annotations

from datetime import timedelta

import pytest

from lgcw.ci.classify import classify
from lgcw.models.base import Strict
from lgcw.models.ci import CiStatus
from lgcw.models.config import Limits, RequiredCheck
from lgcw.models.github import JobView, PrSnapshot, RunView
from tests.unit.ci.cases import NOW, SHA, job, pr, required, run


class Case(Strict):
    """One classification input and its independently specified outcome."""

    name: str
    runs: tuple[RunView, ...] = ()
    jobs: tuple[JobView, ...] = ()
    snapshot: PrSnapshot = pr()
    checks: tuple[RequiredCheck, ...] = required()
    elapsed: int = 0
    expected: CiStatus


CASES = (
    Case(name="no_runs_yet", expected="pending"),
    Case(
        name="required_running",
        runs=(run(status="in_progress", conclusion=None),),
        jobs=(job(status="in_progress", conclusion=None),),
        expected="pending",
    ),
    Case(name="all_green", runs=(run(),), jobs=(job(conclusion="success"),), expected="success"),
    Case(
        name="required_failed", runs=(run(conclusion="failure"),), jobs=(job(),), expected="failure"
    ),
    Case(
        name="cancelled_timeout",
        runs=(run(conclusion="cancelled"),),
        jobs=(job(conclusion="cancelled", annotations=("exceeded the maximum execution time",)),),
        expected="failure",
    ),
    Case(
        name="cancelled_without_timeout",
        runs=(run(conclusion="cancelled"),),
        jobs=(job(conclusion="cancelled"),),
        expected="blocked",
    ),
    Case(
        name="skipped_required",
        runs=(run(),),
        jobs=(job(conclusion="skipped"),),
        expected="blocked",
    ),
    Case(
        name="neutral_required",
        runs=(run(),),
        jobs=(job(conclusion="neutral"),),
        expected="blocked",
    ),
    Case(
        name="head_moved",
        snapshot=pr().model_copy(update={"head_sha": "b" * 40}),
        expected="head_moved",
    ),
    Case(
        name="conflict",
        snapshot=pr().model_copy(update={"mergeable": "CONFLICTING"}),
        expected="conflict",
    ),
    Case(
        name="past_deadline",
        runs=(run(status="queued", conclusion=None),),
        elapsed=5401,
        expected="timeout",
    ),
    Case(
        name="terminal_truth_after_deadline",
        runs=(run(),),
        jobs=(job(conclusion="success"),),
        elapsed=5401,
        expected="success",
    ),
    Case(
        name="old_head_cannot_qualify",
        runs=(run(head="b" * 40),),
        jobs=(job(conclusion="success"),),
        expected="pending",
    ),
    Case(
        name="newer_run_pending",
        runs=(run(), run(identifier=2, status="queued", conclusion=None)),
        jobs=(job(conclusion="success"),),
        expected="pending",
    ),
    Case(
        name="old_attempt_ignored",
        runs=(run(attempt=2),),
        jobs=(job(), job(identifier=2, conclusion="success", attempt=2)),
        expected="success",
    ),
    Case(
        name="missing_job_before_grace",
        runs=(run(),),
        jobs=(job(name="lint", conclusion="success"),),
        expected="pending",
    ),
    Case(
        name="missing_job_after_grace",
        runs=(run(),),
        jobs=(job(name="lint", conclusion="success"),),
        elapsed=601,
        expected="missing",
    ),
    Case(
        name="optional_failure_does_not_replace_required",
        runs=(run(conclusion="failure"),),
        jobs=(job(conclusion="success"), job(identifier=2, name="optional")),
        expected="success",
    ),
    Case(
        name="active_workflow_is_not_green",
        runs=(run(status="in_progress", conclusion=None),),
        jobs=(job(conclusion="success"),),
        expected="pending",
    ),
    Case(
        name="same_name_instances_all_count",
        runs=(run(conclusion="failure"),),
        jobs=(job(), job(identifier=2, conclusion="success")),
        expected="failure",
    ),
    Case(name="empty_required_is_not_empty_green", checks=(), expected="pending"),
    Case(
        name="empty_required_observes_jobs",
        checks=(),
        runs=(run(),),
        jobs=(job(conclusion="success"),),
        expected="success",
    ),
    Case(
        name="workflow_name_collision",
        runs=(run(), run(identifier=2, workflow="Other", conclusion="failure")),
        jobs=(job(conclusion="success"), job(identifier=2, run_id=2, workflow="Other")),
        checks=(*required(), RequiredCheck(workflow="Other", job="test")),
        expected="failure",
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_classify(case: Case) -> None:
    status, failing = classify(
        case.checks,
        case.runs,
        case.jobs,
        case.snapshot,
        SHA,
        NOW,
        NOW + timedelta(seconds=case.elapsed),
        Limits(),
    )
    assert status == case.expected
    if status == "success":
        assert failing == ()


@pytest.mark.unit
def test_classify_missing_after_grace() -> None:
    status, _ = classify(required(), [], [], pr(), SHA, NOW, NOW + timedelta(seconds=601), Limits())
    assert status == "missing"


@pytest.mark.unit
def test_newer_timestamp_supersedes_id_order() -> None:
    newer = run(identifier=1, status="queued", conclusion=None).model_copy(
        update={"created_at": NOW + timedelta(seconds=1)}
    )
    status, _ = classify(
        required(),
        [run(identifier=99), newer],
        [job(run_id=99, conclusion="success")],
        pr(),
        SHA,
        NOW,
        NOW,
        Limits(),
    )
    assert status == "pending"


@pytest.mark.unit
@pytest.mark.parametrize(
    "conclusion,expected",
    [("startup_failure", "failure"), ("action_required", "blocked"), ("cancelled", "blocked")],
)
def test_terminal_run_without_jobs(conclusion: str, expected: CiStatus) -> None:
    status, _ = classify(
        required(), [run(conclusion=conclusion)], [], pr(), SHA, NOW, NOW, Limits()
    )
    assert status == expected


@pytest.mark.unit
def test_active_job_prevents_terminal_run_from_qualifying() -> None:
    status, _ = classify(
        required(),
        [run()],
        [job(status="in_progress", conclusion=None)],
        pr(),
        SHA,
        NOW,
        NOW,
        Limits(),
    )
    assert status == "pending"


@pytest.mark.unit
def test_legacy_runs_without_timestamp_use_attempt_and_id() -> None:
    runs = [
        run().model_copy(update={"created_at": None}),
        run(identifier=2, attempt=2).model_copy(update={"created_at": None}),
    ]
    status, failing = classify(
        required(),
        runs,
        [job(), job(identifier=2, run_id=2, attempt=2, conclusion="success")],
        pr(),
        SHA,
        NOW,
        NOW,
        Limits(),
    )
    assert status == "success" and failing == ()
