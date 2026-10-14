"""Failure prose cannot grant an infrastructure or resource rerun."""

from __future__ import annotations

import pytest

from lgcw.ci.classify import classify
from lgcw.ci.decide import decide
from lgcw.ci.observe import effective_required
from lgcw.models.config import Limits
from tests.unit.ci.cases import NOW, SHA, history, job, pr, repo, run


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "tests/test_pool.py#L42 AssertionError: runner offline state not handled",
        "exit code 137",
        "out of memory",
        "No space left on device",
        "collecting test_intermittent",
        "FAILED test_other - mentions test_intermittent",
        "FAILED test_x - failed to download image fixture",
    ],
)
def test_untrusted_failure_prose_requires_builder_fix(text: str) -> None:
    failed = job(steps=("Test download cache",))
    if text.startswith("tests/"):
        failed = failed.model_copy(
            update={"annotations": (text,), "annotation_paths": ("tests/test_pool.py",)}
        )
    decision = decide(
        "failure",
        [failed],
        [run()],
        [job(conclusion="success")],
        history(),
        [],
        {1: text},
        repo(flaky=("test_intermittent",)),
        Limits(),
        pushed_sha=SHA,
    )
    assert decision.action == "fix"
    assert decision.klass not in {"infra", "resources", "flaky"}


@pytest.mark.unit
def test_same_named_job_cannot_hide_unstarted_required_workflow() -> None:
    runs = [
        run(workflow="Security", conclusion="action_required"),
        run(identifier=2, workflow="Other"),
    ]
    jobs = [job(run_id=2, workflow="Other", name="security", conclusion="success")]
    checks = effective_required((), ("security",), runs, jobs)
    status, _ = classify(checks, runs, jobs, pr(), SHA, NOW, NOW, Limits())
    assert status == "blocked"


@pytest.mark.unit
def test_rerun_class_counts_are_scoped_to_each_head() -> None:
    from lgcw.ci.observe import ci_history
    from lgcw.models.ledger import CiMarker, LedgerEntry, PrLedger

    ledger = PrLedger(
        entries=tuple(
            LedgerEntry(
                marker=CiMarker(
                    head_sha=head, status="failure", klass=klass, action="rerun", fingerprint=None
                ),
                created_at=NOW,
                comment_id=index + 1,
                where="pr",
            )
            for index, (head, klass) in enumerate(((SHA, "infra"), ("b" * 40, "resources")))
        )
    )
    result = ci_history(ledger)
    assert result.reruns_by_class_head == {SHA: {"infra": 1}, "b" * 40: {"resources": 1}}


@pytest.mark.unit
def test_workflow_startup_feedback_has_identity_and_error() -> None:
    from lgcw.ci.feedback import failure_feedback

    failed = run(conclusion="startup_failure").model_copy(
        update={
            "workflow_path": ".github/workflows/broken.yml",
            "startup_error": "invalid syntax at line 4",
        }
    )
    decision = decide(
        "failure",
        [],
        [failed],
        [],
        history(),
        [".github/workflows/broken.yml"],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    feedback = failure_feedback(decision, [], {}, [failed])
    assert decision.action == "fix" and decision.fingerprint is not None
    assert feedback.data is not None
    assert "CI" in feedback.data and ".github/workflows/broken.yml" in feedback.data
    assert "invalid syntax at line 4" in feedback.data


@pytest.mark.unit
def test_workflow_rules_are_not_silently_ignored() -> None:
    from lgcw.github.client import required_contexts_from_rule
    from lgcw.github.port import RequiredPolicyError

    with pytest.raises(RequiredPolicyError, match="workflow"):
        required_contexts_from_rule({"type": "workflows", "parameters": {}})


@pytest.mark.unit
def test_startup_fingerprint_survives_a_new_published_head() -> None:
    failed = run(conclusion="startup_failure")
    first = decide(
        "failure",
        [],
        [failed],
        [],
        history(),
        [".github/workflows/ci.yml"],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    next_head = "c" * 40
    second = decide(
        "failure",
        [],
        [failed.model_copy(update={"head_sha": next_head})],
        [],
        history(),
        [".github/workflows/ci.yml"],
        {},
        repo(),
        Limits(),
        pushed_sha=next_head,
    )
    assert first.fingerprint is not None and first.fingerprint == second.fingerprint


@pytest.mark.unit
def test_small_remaining_feedback_budget_cannot_be_spent_on_annotations() -> None:
    from lgcw.ci.feedback import failure_feedback
    from lgcw.models.ci import CiDecision

    jobs = [job(identifier=1), job(identifier=2), job(identifier=3, annotations=("a" * 20000,))]
    decision = CiDecision(
        head_sha=SHA,
        status="failure",
        klass="change",
        action="fix",
        job=jobs[0],
        fingerprint="fixture",
        note="failure",
    )
    result = failure_feedback(
        decision, jobs, {1: "x" * 7430, 2: "y" * 7430, 3: "Error: third-tail"}, [run()]
    )
    assert result.data is not None and len(result.data.encode()) <= 16384
    assert "third-tail" in result.data
