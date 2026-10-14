"""Compiled CI polling and recovery graphs over timed GitHub fixtures."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.runtime import Runtime

from lgcw.graph.build_graph import STEPS, NodeFn
from lgcw.graph.context import RunContext
from lgcw.graph.nodes import DEFAULT_NODES
from lgcw.graph.nodes.ci_wait import ci_wait
from lgcw.graph.runner import run_issue
from lgcw.ledger.markers import render_marker
from lgcw.models.base import Step
from lgcw.models.ledger import CiMarker
from lgcw.models.state import RunOutcome, RunState
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import EditingHarness, execute, markers, output, setup
from tests.unit.ci.cases import job, run, runner_job


async def published(case: GraphCase) -> tuple[RunContext, EditingHarness, str]:
    """Publish a real local fixture change through the implemented build/gate graph."""
    ctx, harness = await setup(case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    assert await execute(ctx) == "waiting"
    head = (await ctx.github.get_pr(ctx.issue_ref.repo, 100)).head_sha
    return ctx, harness, head


async def execute_ci(ctx: RunContext) -> RunOutcome:
    """Run CI with actual build fixes and an explicit future-review checkpoint."""

    async def checkpoint(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        runtime.context.log.event("unit_checkpoint", node="review")
        return {"next_step": "end", "outcome": "waiting"}

    mapping: dict[Step, NodeFn] = {step: checkpoint for step in STEPS if step != "end"}
    mapping.update(DEFAULT_NODES)
    mapping["ci_wait"] = ci_wait
    mapping["review"] = checkpoint  # T16 lifecycle migration authorized by comment6160199995.
    return await run_issue(ctx, nodes=mapping)


def script_failure(case: GraphCase, head: str, *, infrastructure: bool = False) -> None:
    """Install one completed failed job with typed annotation/setup evidence."""
    case.github.runs[head] = [run(head=head, conclusion="failure")]
    case.github.jobs[1] = [
        runner_job(annotations=("The runner lost communication",)) if infrastructure else job()
    ]
    case.github.logs[1] = "##[group]Run tests\nError: introduced failure\n##[endgroup]"
    case.github.base_jobs[(case.ctx.issue_ref.repo, "CI", "main")] = [
        job(identifier=10, conclusion="success")
    ]


@pytest.mark.unit
async def test_pending_then_success_goes_to_review(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.script_runs(
        head,
        [
            (0, [run(head=head, status="in_progress", conclusion=None)], []),
            (15, [run(head=head)], [job(conclusion="success")]),
        ],
    )
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ci")[-1].status == "success"
    assert markers(graph_case, "ci")[-1].action == "proceed_note"
    assert len(harness.turns) == 1 and not graph_case.github.rerun_requests


@pytest.mark.unit
async def test_change_failure_sends_trimmed_log_to_builder(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.github.logs[1] = (
        "##[group]Run tests\nError: meaningful-ci-fixture\n" + "detail\n" * 4000
    )
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    assert len(harness.turns) == 2
    text = harness.turns[1][1].text
    assert "meaningful-ci-fixture" in text and "release 0.1.1" in text
    assert len(text.encode()) < 20000
    assert markers(graph_case, "push")[-1].source == "ci_fix"
    assert markers(graph_case, "feedback")[-1].feedback.source == "ci"


@pytest.mark.unit
async def test_same_ci_failure_after_fix_restarts_then_asks(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.workspace.after_push = lambda sha: script_failure(graph_case, sha)
    harness.edits.extend([{"app.py": "VERSION = '0.1.2'\n"}, {"app.py": "VERSION = '0.1.3'\n"}])
    harness.script("builder", [output("app.py")] * 2)
    assert await execute_ci(ctx) == "waiting"
    assert len(harness.turns) == 3
    assert len(markers(graph_case, "session")) == 2
    assert markers(graph_case, "session")[-1].cause.startswith("failure:")
    assert markers(graph_case, "ask")[-1].code == "builder_restart_limit"


@pytest.mark.unit
async def test_infra_rerun_once_then_success(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.script_runs(
        head,
        [
            (
                0,
                [run(head=head, conclusion="failure")],
                [runner_job(annotations=("The runner lost communication",))],
            ),
            (15, [run(head=head, attempt=2)], [job(conclusion="success", attempt=2)]),
        ],
    )
    assert await execute_ci(ctx) == "waiting"
    assert sum(graph_case.github.rerun_requests.values()) == 1
    assert markers(graph_case, "ci")[-1].status == "success" and len(harness.turns) == 1


@pytest.mark.unit
async def test_pre_existing_failure_moves_on_with_note(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.github.base_jobs[(ctx.issue_ref.repo, "CI", "main")] = [job(identifier=10)]
    assert await execute_ci(ctx) == "waiting"
    decision = markers(graph_case, "ci")[-1]
    assert decision.klass == "pre_existing" and decision.action == "proceed_note"
    assert len(harness.turns) == 1
    assert not graph_case.github.rerun_requests


@pytest.mark.unit
async def test_missing_after_grace_asks(graph_case: GraphCase) -> None:
    ctx, harness, _ = await published(graph_case)
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_missing"
    assert len(harness.turns) == 1
    assert (
        ctx.clock.now() - graph_case.github.comments[(ctx.issue_ref.repo, 100)][0].created_at
    ).total_seconds() >= ctx.config.limits.ci_start_grace_s


@pytest.mark.unit
async def test_deadline_asks(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.runs[head] = [run(head=head, status="in_progress", conclusion=None)]
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_timeout"
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_decision_reused_after_crash(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.script_runs(
        head,
        [
            (
                0,
                [run(head=head, conclusion="failure")],
                [runner_job(annotations=("The runner lost communication",))],
            ),
            (15, [run(head=head, attempt=2)], [job(conclusion="success", attempt=2)]),
        ],
    )
    graph_case.github.fail_after("rerun_failed_jobs", 1, InjectedCrash("rerun response lost"))
    with pytest.raises(InjectedCrash):
        await execute_ci(ctx)
    assert sum(graph_case.github.rerun_requests.values()) == 1
    assert await execute_ci(ctx) == "waiting"
    assert sum(graph_case.github.rerun_requests.values()) == 1
    reruns = [m for m in markers(graph_case, "ci") if m.action == "rerun"]
    assert len(reruns) == 1 and len(harness.turns) == 1
    assert markers(graph_case, "ci")[-1].status == "success"


@pytest.mark.unit
async def test_rerun_cap_per_pr(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    policy = ctx.config.model_copy(
        update={"limits": ctx.config.limits.model_copy(update={"reruns_per_pr": 1})}
    )
    ctx = ctx.model_copy(update={"config": policy})
    old = CiMarker(
        head_sha="e" * 40, status="failure", klass="infra", action="rerun", fingerprint="prior"
    )
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, render_marker(old))
    script_failure(graph_case, head, infrastructure=True)
    assert await execute_ci(ctx) == "waiting"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 1
    assert markers(graph_case, "ci")[-1].action == "ask"


@pytest.mark.unit
async def test_ruleset_job_union_is_used_by_classifier_and_decider(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.required_contexts[(ctx.issue_ref.repo, "main")] = ("security",)
    graph_case.github.runs[head] = [
        run(head=head),
        run(identifier=2, workflow="Security", head=head, conclusion="action_required"),
    ]
    graph_case.github.jobs[1] = [job(conclusion="success")]
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ci")[-1].klass == "awaiting_approval"
    assert markers(graph_case, "ask") and len(harness.turns) == 1


@pytest.mark.unit
@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
async def test_ci_comment_crash_boundaries_never_repeat_dispatch(
    graph_case: GraphCase, boundary: int
) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.script_runs(
        head,
        [
            (
                0,
                [run(head=head, conclusion="failure")],
                [runner_job(annotations=("The runner lost communication",))],
            ),
            (15, [run(head=head, attempt=2)], [job(conclusion="success", attempt=2)]),
        ],
    )
    graph_case.github.fail_after("create_issue_comment", boundary, InjectedCrash("CI receipt lost"))
    with pytest.raises(InjectedCrash):
        await execute_ci(ctx)
    assert await execute_ci(ctx) == "waiting"
    assert sum(graph_case.github.rerun_requests.values()) == (0 if boundary == 2 else 1)
    if boundary == 2:
        assert markers(graph_case, "ask")[-1].code == "ci_rerun_unknown"
    else:
        assert markers(graph_case, "ci")[-1].status == "success"
    assert len([m for m in markers(graph_case, "ci") if m.action == "rerun"]) == 1
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_unknown_rerun_intent_waits_then_asks_without_dispatch(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head, infrastructure=True)
    graph_case.github.fail_after("create_issue_comment", 2, InjectedCrash("intent response lost"))
    with pytest.raises(InjectedCrash):
        await execute_ci(ctx)
    assert not graph_case.github.rerun_requests
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_rerun_unknown"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 1
    # A human starts the missing attempt in Actions, then explicitly resumes the workflow.
    graph_case.github.runs[head] = [run(head=head, attempt=2)]
    graph_case.github.jobs[1] = [job(conclusion="success", attempt=2)]
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ci")[-1].status == "success"
    assert not graph_case.github.rerun_requests


@pytest.mark.unit
async def test_ruleset_missing_job_never_passes_on_configured_green(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.required_contexts[(ctx.issue_ref.repo, "main")] = ("security",)
    graph_case.github.runs[head] = [run(head=head)]
    graph_case.github.jobs[1] = [job(conclusion="success")]
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_missing"
    assert not any(m.status == "success" for m in markers(graph_case, "ci"))
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_unpublished_workflow_file_cannot_turn_startup_failure_into_builder_fix(
    graph_case: GraphCase,
) -> None:
    ctx, harness, head = await published(graph_case)
    path = harness.root / ".github/workflows/unpublished.yml"
    path.parent.mkdir(parents=True)
    path.write_text("name: uncommitted owner work\n")
    graph_case.github.runs[head] = [run(head=head, conclusion="startup_failure")]
    assert await execute_ci(ctx) == "waiting"
    decision = markers(graph_case, "ci")[-1]
    assert decision.klass == "startup_failure" and decision.action == "ask"
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 2
    assert path.read_text() == "name: uncommitted owner work\n"
