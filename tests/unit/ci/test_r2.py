"""CI evidence and transient-cost regressions from review R2."""

from __future__ import annotations

import pytest

from lgcw.ci.decide import decide
from lgcw.ci.logs import clean_evidence
from lgcw.models.config import Limits
from lgcw.models.github import JobStep
from tests.unit.ci.cases import SHA, history, job, repo, run


@pytest.mark.unit
@pytest.mark.parametrize("path", [".github", None, ".github/workflows/ci.yml"])
@pytest.mark.parametrize("field", ["annotation", "service_output"])
def test_user_step_cannot_forge_runner_provenance(path: str | None, field: str) -> None:
    failed = job(annotations=("The runner lost communication",)).model_copy(
        update={
            "annotation_paths": (path,),
            "service_output": "The runner lost communication" if field == "service_output" else "",
            "steps": (
                JobStep(number=1, name="Set up job", status="completed", conclusion="success"),
                JobStep(number=2, name="Set up job", status="completed", conclusion="failure"),
            ),
        }
    )
    result = decide(
        "failure",
        [failed],
        [run()],
        [],
        history(),
        [],
        {1: "FAILED real_regression"},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "fix" and result.klass != "infra"


@pytest.mark.unit
@pytest.mark.parametrize("prior", ["infra", "resources", "flaky"])
def test_any_failed_transient_rerun_reaches_builder(prior: str) -> None:
    from lgcw.models.ci import CiHistory

    past = CiHistory.model_validate(
        {
            "reruns_by_head": {SHA: 1},
            "reruns_total": 1,
            "ci_fix_rounds": 0,
            "fingerprints": [],
            "reruns_by_class_head": {SHA: {prior: 1}},
        }
    )
    failed = job(annotations=("The runner lost communication",)).model_copy(
        update={
            "steps": (
                JobStep(number=1, name="Set up job", status="completed", conclusion="failure"),
            )
        }
    )
    result = decide(
        "failure", [failed], [run()], [], past, [], {}, repo(), Limits(), pushed_sha=SHA
    )
    assert result.action == "fix"


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,number", [("Install dependencies", 2), ("Set up job", 2), ("Set up job extra", 1)]
)
def test_user_setup_names_do_not_authorize_infra(name: str, number: int) -> None:
    failed = job(steps=(name,)).model_copy(
        update={
            "steps": (JobStep(number=number, name=name, status="completed", conclusion="failure"),)
        }
    )
    result = decide(
        "failure",
        [failed],
        [run()],
        [],
        history(),
        [],
        {1: "Could not resolve host example.test"},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "fix" and result.klass != "infra"


@pytest.mark.unit
def test_network_error_in_other_step_is_not_infra() -> None:
    failed = job(steps=("Install dependencies",)).model_copy(
        update={
            "steps": (
                JobStep(
                    number=2, name="Install dependencies", status="completed", conclusion="failure"
                ),
            )
        }
    )
    result = decide(
        "failure",
        [failed],
        [run()],
        [],
        history(),
        [],
        {
            1: "##[group]Run tests\nCould not resolve host example.test\n"
            "##[group]Set up job\nError: actual regression"
        },
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "fix" and result.klass != "infra"


@pytest.mark.unit
@pytest.mark.parametrize("sequence", ["\x1bP", "\x1b^", "\x1b_", "\x1bX", "\x1b]52;c;"])
def test_control_removal_is_line_bounded_and_retains_classifier_input(sequence: str) -> None:
    raw = "FAILED known_flaky\n" + sequence + "\nFAILED real_regression"
    clean = clean_evidence(raw)
    assert "FAILED real_regression" in clean and "terminal control removed" in clean
    result = decide(
        "failure",
        [job()],
        [run()],
        [],
        history(),
        [],
        {1: clean},
        repo(flaky=("known_flaky",)),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "fix"


@pytest.mark.unit
@pytest.mark.parametrize(
    "extra",
    ["ERROR collecting tests/test_other.py", "error TS1234: broken", "FAIL package/test", ""],
)
def test_flaky_requires_complete_pytest_summary_without_other_errors(extra: str) -> None:
    log = "FAILED known_flaky\n" + extra
    result = decide(
        "failure",
        [job()],
        [run()],
        [],
        history(),
        [],
        {1: log},
        repo(flaky=("known_flaky",)),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "fix" and result.klass != "flaky"


@pytest.mark.unit
def test_full_jobs_still_name_the_omitted_third_failure() -> None:
    from lgcw.ci.feedback import failure_feedback
    from lgcw.models.ci import CiDecision

    jobs = [job(identifier=i, name=f"failure-{i}", annotations=("a" * 6000,)) for i in (1, 2, 3)]
    decision = CiDecision(
        head_sha=SHA,
        status="failure",
        klass="change",
        action="fix",
        job=jobs[0],
        fingerprint="fixture",
        note="failure",
    )
    feedback = failure_feedback(
        decision, jobs, {i: "Error: " + str(i) + "x" * 12000 for i in (1, 2, 3)}, [run()]
    )
    assert feedback.data is not None and len(feedback.data.encode()) <= 16384
    assert "also failing (omitted): CI/failure-3" in feedback.data


@pytest.mark.unit
@pytest.mark.parametrize("rule", ["required_deployments", "code_scanning", "merge_queue"])
def test_non_actions_required_rules_fail_closed(rule: str) -> None:
    from lgcw.github.client import required_contexts_from_rule
    from lgcw.github.port import RequiredPolicyError

    with pytest.raises(RequiredPolicyError, match=rule):
        required_contexts_from_rule({"type": rule, "parameters": {}})


@pytest.mark.unit
@pytest.mark.parametrize(
    "log",
    [
        "FAILED known_flaky\nFAILED real_regression\n=== 2 failed in 0.2s ===",
        "FAILED known_flaky\n=== 2 failed in 0.2s ===",
        "FAILED known_flaky\nERROR collecting tests/test_other.py\n"
        "=== 1 failed, 1 error in 0.2s ===",
    ],
)
def test_flaky_subset_summary_and_errors(log: str) -> None:
    result = decide(
        "failure",
        [job()],
        [run()],
        [],
        history(),
        [],
        {1: log},
        repo(flaky=("known_flaky",)),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "fix" and result.klass != "flaky"


@pytest.mark.unit
@pytest.mark.parametrize("guard", ["annotation", "job", "selected"])
def test_feedback_independent_bounds_and_selected_first(guard: str) -> None:
    from lgcw.ci.feedback import failure_feedback
    from lgcw.models.ci import CiDecision

    jobs = [job(identifier=i, name=f"job-{i}", annotations=("A" * 40000,)) for i in (1, 2, 3)]
    selected = jobs[2] if guard == "selected" else jobs[0]
    decision = CiDecision(
        head_sha=SHA,
        status="failure",
        klass="change",
        action="fix",
        job=selected,
        fingerprint="fixture",
        note="failure",
    )
    result = failure_feedback(
        decision,
        jobs if guard == "selected" else [selected],
        {i: "Error: retained\n" + "x" * 20000 for i in (1, 2, 3)},
        [run()],
    )
    assert result.data is not None
    if guard == "annotation":
        annotation = result.data.split("Annotations: ", 1)[1].split("\n", 1)[0]
        assert len(annotation.encode()) <= 2048
    elif guard == "job":
        assert len(result.data.encode()) <= 8192
    else:
        assert result.data.startswith("Workflow: CI; job: job-3;")
        assert "retained" in result.data and len(result.data.encode()) <= 16384


@pytest.mark.unit
def test_execution_base_ref_must_match_current_pr() -> None:
    from lgcw.ci.classify import owned_runs
    from lgcw.models.github import RunPullRequest
    from tests.unit.ci.cases import pr

    current = pr().model_copy(update={"number": 100})
    other_base = run().model_copy(
        update={"pr_associations": (RunPullRequest(number=100, base_ref="release"),)}
    )
    assert owned_runs([run()], "example/sandbox", current) == (run(),)
    assert owned_runs([other_base], "example/sandbox", current) == ()


@pytest.mark.unit
def test_no_user_step_started_cancel_is_an_infra_failure() -> None:
    from lgcw.ci.classify import classify
    from tests.unit.ci.cases import NOW, pr, required

    failed = job(conclusion="cancelled", steps=()).model_copy(update={"steps_observed": True})
    status, failing = classify(
        required(), [run(conclusion="cancelled")], [failed], pr(), SHA, NOW, NOW, Limits()
    )
    assert status == "failure"
    result = decide(
        status, failing, [run()], [], history(), [], {}, repo(), Limits(), pushed_sha=SHA
    )
    assert (result.klass, result.action) == ("infra", "rerun")


@pytest.mark.unit
def test_pinned_real_annotation_path_does_not_make_user_failure_infra() -> None:
    import json
    from pathlib import Path

    from lgcw.github.client import job_from_rest

    fixture = Path(__file__).parents[2] / "fixtures" / "ci" / "provenance-observation.json"
    observed = json.loads(fixture.read_text())
    failed = job_from_rest(
        {
            "id": 1,
            "run_id": 1,
            "workflow_name": "CI",
            "name": "test",
            "status": "completed",
            "conclusion": "failure",
            "run_attempt": 1,
            "steps": observed["steps"],
            "service_output": observed["service_output"],
            "html_url": "https://example.test/job",
        },
        observed["annotations"],
    )
    assert failed.annotation_paths == (".github", ".github")
    assert failed.steps[0].number == 1 and failed.steps[0].conclusion == "success"
    result = decide(
        "failure",
        [failed],
        [run()],
        [job(conclusion="success")],
        history(),
        [],
        {1: "Error: real user-command failure"},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "fix" and result.klass != "infra"


@pytest.mark.unit
def test_missing_step_number_does_not_prove_no_user_work() -> None:
    from lgcw.ci.classify import no_user_steps_started
    from lgcw.github.client import job_from_rest

    failed = job_from_rest(
        {
            "id": 1,
            "run_id": 1,
            "workflow_name": "CI",
            "name": "test",
            "status": "completed",
            "conclusion": "cancelled",
            "run_attempt": 1,
            "html_url": "https://example.test/job",
            "steps": [{"name": "Run tests", "status": "completed", "conclusion": "cancelled"}],
        },
        [],
    )
    assert not failed.steps_observed
    assert not no_user_steps_started(failed)
