"""Every CI table row, action aggregation, and independently bounded retry classes."""

from __future__ import annotations

import pytest

from lgcw.ci.decide import decide
from lgcw.models.base import Strict
from lgcw.models.ci import CiAction, CiClass, CiHistory, CiStatus
from lgcw.models.config import Limits, RepoConfig
from lgcw.models.github import JobView, RunView
from tests.unit.ci.cases import SHA, history, job, repo, run, runner_job


class Case(Strict):
    """A decision-table signal with a fixed expected class and action."""

    name: str
    status: CiStatus = "failure"
    failing: tuple[JobView, ...] = (job(),)
    runs: tuple[RunView, ...] = (run(conclusion="failure"),)
    base: tuple[JobView, ...] | None = None
    past: CiHistory = history()
    paths: tuple[str, ...] = ()
    logs: dict[int, str] = {}
    config: RepoConfig = repo()
    expected_class: CiClass | None
    expected_action: CiAction


CASES = (
    Case(
        name="superseded",
        status="blocked",
        runs=(run(head="b" * 40),),
        failing=(),
        expected_class="superseded",
        expected_action="wait",
    ),
    Case(
        name="awaiting_approval",
        status="blocked",
        runs=(run(conclusion="action_required"),),
        failing=(),
        expected_class="awaiting_approval",
        expected_action="ask",
    ),
    Case(
        name="startup_workflow_changed",
        runs=(run(conclusion="startup_failure"),),
        failing=(),
        paths=(".github/workflows/ci.yml",),
        expected_class="startup_failure",
        expected_action="fix",
    ),
    Case(
        name="startup_external",
        runs=(run(conclusion="startup_failure"),),
        failing=(),
        expected_class="startup_failure",
        expected_action="ask",
    ),
    Case(
        name="infra_setup_network",
        failing=(runner_job(),),
        logs={1: "##[group]Set up job\nCould not resolve host registry.example.test"},
        expected_class="infra",
        expected_action="rerun",
    ),
    Case(
        name="network_in_test_is_change",
        base=(job(conclusion="success"),),
        logs={1: "Could not resolve host test-service.example.test"},
        expected_class="change",
        expected_action="fix",
    ),
    Case(
        name="timeout_base_too",
        failing=(job(conclusion="cancelled", annotations=("has timed out",)),),
        base=(job(conclusion="cancelled", annotations=("has timed out",)),),
        expected_class="timeout",
        expected_action="rerun",
    ),
    Case(
        name="timeout_new",
        failing=(job(conclusion="cancelled", annotations=("has timed out",)),),
        base=(job(conclusion="success"),),
        expected_class="timeout",
        expected_action="fix",
    ),
    Case(
        name="resources",
        failing=(runner_job(annotations=("ENOSPC: no space left on device",)),),
        logs={1: "ENOSPC: no space left on device"},
        expected_class="resources",
        expected_action="rerun",
    ),
    Case(
        name="known_flaky",
        config=repo(flaky=("test_intermittent",)),
        logs={1: "FAILED test_intermittent\n=== 1 failed in 0.1s ==="},
        expected_class="flaky",
        expected_action="rerun",
    ),
    Case(
        name="pre_existing",
        base=(job(),),
        expected_class="pre_existing",
        expected_action="proceed_note",
    ),
    Case(
        name="pre_existing_ask",
        base=(job(),),
        config=repo(policy="ask"),
        expected_class="pre_existing",
        expected_action="ask",
    ),
    Case(
        name="mass_failure",
        failing=tuple(job(identifier=index, name=f"job-{index}") for index in range(1, 6)),
        expected_class="mass_failure",
        expected_action="fix",
    ),
    Case(
        name="change",
        base=(job(conclusion="success"),),
        expected_class="change",
        expected_action="fix",
    ),
    Case(
        name="unclassified",
        failing=(job(steps=("Publish",)),),
        expected_class="unclassified",
        expected_action="fix",
    ),
    Case(
        name="missing",
        status="missing",
        failing=(),
        runs=(),
        expected_class=None,
        expected_action="ask",
    ),
    Case(name="pending", status="pending", failing=(), expected_class=None, expected_action="wait"),
    Case(
        name="success",
        status="success",
        failing=(),
        expected_class=None,
        expected_action="proceed_note",
    ),
    Case(
        name="flaky_passed",
        status="success",
        failing=(),
        past=history(reruns=1, total=1, classes={"flaky": 1}),
        expected_class="flaky",
        expected_action="proceed_note",
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_decide(case: Case) -> None:
    result = decide(
        case.status,
        case.failing,
        case.runs,
        case.base,
        case.past,
        case.paths,
        case.logs,
        case.config,
        Limits(),
        pushed_sha=SHA,
    )
    assert (result.klass, result.action) == (case.expected_class, case.expected_action)
    assert result.head_sha == SHA


@pytest.mark.unit
@pytest.mark.parametrize(
    "past",
    [
        history(reruns=2, total=2),
        history(total=5),
        history(reruns=1, total=1, classes={"infra": 1}),
        history(reruns=1, total=1),
    ],
)
def test_rerun_caps(past: CiHistory) -> None:
    result = decide(
        "failure",
        [runner_job()],
        [run()],
        None,
        past,
        [],
        {1: "runner lost connection"},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == ("fix" if past.reruns_by_head.get(SHA, 0) else "ask")


@pytest.mark.unit
def test_resource_repeat_goes_to_builder() -> None:
    result = decide(
        "failure",
        [runner_job(annotations=("out of memory",))],
        [run()],
        None,
        history(reruns=1, total=1, classes={"resources": 1}),
        [],
        {1: "out of memory"},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert (result.klass, result.action) == ("resources", "fix")


@pytest.mark.unit
def test_ci_fix_round_cap() -> None:
    result = decide(
        "failure",
        [job()],
        [run()],
        [job(conclusion="success")],
        history(fixes=3),
        [],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "ask"


@pytest.mark.unit
def test_pre_existing_does_not_hide_another_regression() -> None:
    current = [job(), job(identifier=2, name="second")]
    baseline = [job(), job(identifier=2, name="second", conclusion="success")]
    result = decide(
        "failure", current, [run()], baseline, history(), [], {}, repo(), Limits(), pushed_sha=SHA
    )
    assert (result.klass, result.action) == ("change", "fix")


@pytest.mark.unit
@pytest.mark.parametrize("status", ["conflict", "head_moved", "missing", "timeout"])
def test_qualification_guards_ask(status: CiStatus) -> None:
    result = decide(status, [], [], None, history(), [], {}, repo(), Limits(), pushed_sha=SHA)
    assert result.action == "ask" and result.head_sha == SHA


@pytest.mark.unit
def test_startup_fix_obeys_fix_cap() -> None:
    result = decide(
        "failure",
        [],
        [run(conclusion="startup_failure")],
        None,
        history(fixes=3),
        [".github/workflows/ci.yml"],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "ask"


@pytest.mark.unit
def test_blocked_without_job_evidence_asks() -> None:
    result = decide(
        "blocked",
        [],
        [run(conclusion="cancelled")],
        None,
        history(),
        [],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert (result.klass, result.action) == ("unclassified", "ask")


@pytest.mark.unit
def test_skipped_required_job_is_never_a_builder_fix() -> None:
    result = decide(
        "blocked",
        [job(conclusion="skipped")],
        [run()],
        None,
        history(),
        [],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "ask"


@pytest.mark.unit
@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "neutral"])
def test_failed_run_consequences_do_not_hide_real_failure(conclusion: str) -> None:
    result = decide(
        "failure",
        [job(), job(identifier=2, name="dependent", conclusion=conclusion)],
        [run(conclusion="failure")],
        [job(conclusion="success")],
        history(),
        [],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert (result.klass, result.action) == ("change", "fix")


@pytest.mark.unit
@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "neutral"])
def test_five_blocked_jobs_never_become_mass_failure(conclusion: str) -> None:
    result = decide(
        "blocked",
        [job(identifier=i, name=f"job-{i}", conclusion=conclusion) for i in range(5)],
        [run()],
        None,
        history(),
        [],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert result.action == "ask" and result.klass != "mass_failure"


@pytest.mark.unit
@pytest.mark.parametrize("conclusion", ["startup_failure", "action_required"])
def test_optional_run_does_not_override_required_failure(conclusion: str) -> None:
    result = decide(
        "failure",
        [job()],
        [run(conclusion="failure"), run(identifier=2, workflow="Optional", conclusion=conclusion)],
        [job(conclusion="success")],
        history(),
        [],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert (result.klass, result.action) == ("change", "fix")


@pytest.mark.unit
@pytest.mark.parametrize("attempt", [False, True])
def test_old_base_failure_does_not_hide_introduced_failure(attempt: bool) -> None:
    old = job(run_id=10)
    newer = job(run_id=10 if attempt else 11, attempt=2 if attempt else 1, conclusion="success")
    result = decide(
        "failure",
        [job()],
        [run(conclusion="failure")],
        [old, newer],
        history(),
        [],
        {},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert (result.klass, result.action) == ("change", "fix")
