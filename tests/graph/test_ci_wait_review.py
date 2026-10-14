"""Reviewer reproductions for durable, provenance-bound CI observation."""

from __future__ import annotations

import pytest

from lgcw.models.github import IssueComment
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import markers
from tests.graph.test_ci_wait import execute_ci, published
from tests.unit.ci.cases import job, run


@pytest.mark.unit
async def test_rerun_decision_without_intent_resumes_exact_dispatch(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.logs[1] = "Runner lost communication before tests."
    graph_case.github.script_runs(
        head,
        [
            (
                0,
                [run(head=head, conclusion="failure")],
                [job(annotations=("The runner lost communication",))],
            ),
            (15, [run(head=head, attempt=2)], [job(conclusion="success", attempt=2)]),
        ],
    )
    graph_case.github.fail_after("create_issue_comment", 1, InjectedCrash("decision receipt lost"))
    with pytest.raises(InjectedCrash):
        await execute_ci(ctx)
    assert not graph_case.github.rerun_requests
    assert await execute_ci(ctx) == "waiting"
    assert sum(graph_case.github.rerun_requests.values()) == 1
    assert markers(graph_case, "ci")[-1].status == "success"
    assert len(harness.turns) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "override",
    [
        {"event": "workflow_dispatch"},
        {"head_repository": "fork/sandbox"},
        {"head_branch": "owner-other-branch"},
        {"pull_requests": (999,)},
    ],
)
async def test_impostor_run_never_dispatched(
    graph_case: GraphCase, override: dict[str, object]
) -> None:
    ctx, harness, head = await published(graph_case)
    graph_case.github.runs[head] = [
        run(head=head),
        run(identifier=999, head=head, conclusion="failure").model_copy(update=override),
    ]
    graph_case.github.jobs[1] = [job(conclusion="success")]
    graph_case.github.jobs[999] = [job(identifier=999, run_id=999, annotations=("runner offline",))]
    assert await execute_ci(ctx) == "waiting"
    assert not graph_case.github.rerun_requests
    assert markers(graph_case, "ci")[-1].status == "success"
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_test_annotation_still_downloads_log_and_fixes(graph_case: GraphCase) -> None:
    from tests.graph.test_build_gate_publish import output
    from tests.graph.test_ci_wait import script_failure

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.github.jobs[1] = [
        job(annotations=("runner lost communication",)).model_copy(
            update={"annotation_paths": ("tests/test_pool.py",)}
        )
    ]
    graph_case.github.logs[1] = "FAILED tests/test_pool.py - actual-regression-evidence"
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    assert any(method == "job_log" for method, _ in graph_case.github.calls)
    assert not graph_case.github.rerun_requests
    assert "actual-regression-evidence" in harness.turns[1][1].text


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["\x01" * 16384, "-" * 16384], ids=["controls", "dashes"])
async def test_escaped_feedback_marker_stays_bounded(graph_case: GraphCase, raw: str) -> None:
    from lgcw.ledger.markers import render_marker
    from tests.graph.test_build_gate_publish import output
    from tests.graph.test_ci_wait import script_failure

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.github.logs[1] = raw + "\nError: terminal-evidence"
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    feedback = markers(graph_case, "feedback")[-1]
    assert len(render_marker(feedback)) < 59000
    assert "\x01" not in feedback.feedback.data
    assert "terminal-evidence" in feedback.feedback.data
    assert len(harness.turns) == 2


@pytest.mark.unit
async def test_two_jobs_keep_log_evidence_under_long_annotation(graph_case: GraphCase) -> None:
    from tests.graph.test_build_gate_publish import output
    from tests.graph.test_ci_wait import script_failure

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.github.required_contexts[(ctx.issue_ref.repo, "main")] = ("lint-second",)
    graph_case.github.jobs[1] = [
        job(annotations=("annotation " * 2000,)),
        job(identifier=2, name="lint-second"),
    ]
    graph_case.github.logs[1] = "Error: first-job-evidence"
    graph_case.github.logs[2] = "Error: lint-second-job-evidence"
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    data = markers(graph_case, "feedback")[-1].feedback.data
    assert "first-job-evidence" in data and "lint-second-job-evidence" in data
    assert data.count("Workflow:") == 2 and data.count("Failed steps:") == 2
    assert len(data.encode()) <= 16384


@pytest.mark.unit
async def test_rerun_cap_per_head_with_different_class(graph_case: GraphCase) -> None:
    from lgcw.ledger.markers import render_marker
    from lgcw.models.ledger import CiMarker
    from tests.graph.test_ci_wait import script_failure

    ctx, harness, head = await published(graph_case)
    ctx = ctx.model_copy(
        update={
            "config": ctx.config.model_copy(
                update={"limits": ctx.config.limits.model_copy(update={"reruns_per_head": 1})}
            )
        }
    )
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo,
        100,
        render_marker(
            CiMarker(
                head_sha=head,
                status="failure",
                klass="resources",
                action="rerun",
                fingerprint=None,
                run_id=99,
                run_attempt=1,
            )
        ),
    )
    script_failure(graph_case, head, infrastructure=True)
    assert await execute_ci(ctx) == "waiting"
    assert not graph_case.github.rerun_requests
    assert markers(graph_case, "ask")[-1].code == "ci_failure"
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_pending_rerun_on_old_head_is_ignored(graph_case: GraphCase) -> None:
    from lgcw.ledger.markers import render_marker
    from lgcw.models.ledger import RerunMarker

    ctx, harness, head = await published(graph_case)
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo,
        100,
        render_marker(
            RerunMarker(
                operation_id="old-head-op",
                head_sha="b" * 40,
                run_id=99,
                from_attempt=1,
                phase="intent",
            )
        ),
    )
    graph_case.github.runs[head] = [run(head=head)]
    graph_case.github.jobs[1] = [job(conclusion="success")]
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ci")[-1].status == "success"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 1


@pytest.mark.unit
async def test_required_policy_error_asks_specific_code(graph_case: GraphCase) -> None:
    from lgcw.github.port import RequiredPolicyError

    ctx, harness, head = await published(graph_case)
    graph_case.github.runs[head] = [run(head=head)]
    graph_case.github.jobs[1] = [job(conclusion="success")]
    graph_case.github.fail_after("required_check_contexts", 1, RequiredPolicyError("external app"))
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_policy_unsupported"
    assert len(harness.turns) == 1 and not graph_case.github.rerun_requests


@pytest.mark.unit
@pytest.mark.parametrize("boundary", ["initial-pr", "observation", "dispatch"])
async def test_head_move_during_ci_stops_before_dispatch(
    graph_case: GraphCase, boundary: str
) -> None:
    from lgcw.ledger.markers import parse_markers
    from tests.graph.test_ci_wait import script_failure

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head, infrastructure=True)

    def move() -> None:
        graph_case.github.branch_heads[(ctx.issue_ref.repo, "lgcw/issue-1")] = "f" * 40

    def after_call(method: str) -> None:
        if (boundary == "initial-pr" and method == "get_pr") or (
            boundary == "observation" and method == "runs_for_sha"
        ):
            move()

    def after_comment(comment: IssueComment) -> None:
        if boundary == "dispatch" and any(
            marker.kind == "rerun" for marker in parse_markers(comment.body)
        ):
            move()

    before = len(graph_case.github.calls)
    graph_case.github.after_call = after_call
    graph_case.github.after_comment = after_comment
    assert await execute_ci(ctx) == "waiting"
    if boundary == "initial-pr":
        assert not any(method == "runs_for_sha" for method, _ in graph_case.github.calls[before:])
    if boundary == "observation":
        assert not markers(graph_case, "ci")
    assert not graph_case.github.rerun_requests
    assert markers(graph_case, "ask")[-1].code == "head_moved"
    assert markers(graph_case, "ask")[-1].step == "reconcile"
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_ci_closed_pr_does_not_poll(graph_case: GraphCase) -> None:
    ctx, harness, _ = await published(graph_case)
    before = len(graph_case.github.calls)

    def close(method: str) -> None:
        if method == "find_pr":
            key = (ctx.issue_ref.repo, 100)
            graph_case.github.prs[key] = graph_case.github.prs[key].model_copy(
                update={"state": "CLOSED"}
            )

    graph_case.github.after_call = close
    assert await execute_ci(ctx) == "closed"
    assert not any(method == "runs_for_sha" for method, _ in graph_case.github.calls[before:])
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_ci_fix_retry_grants_exactly_one_round(graph_case: GraphCase) -> None:
    from lgcw.ledger.markers import render_marker
    from lgcw.models.ledger import PushMarker
    from tests.graph.test_build_gate_publish import output
    from tests.graph.test_ci_wait import script_failure

    ctx, harness, head = await published(graph_case)
    for round_number in (1, 2, 3):
        await ctx.github.create_issue_comment(
            ctx.issue_ref.repo,
            100,
            render_marker(PushMarker(head_sha=head, round=round_number, source="ci_fix")),
        )
    script_failure(graph_case, head)
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_fix_limit"
    assert len(harness.turns) == 1
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    graph_case.workspace.after_push = lambda sha: script_failure(graph_case, sha)
    assert await execute_ci(ctx) == "waiting"
    assert len(harness.turns) == 2
    assert markers(graph_case, "ask")[-1].code == "ci_fix_limit"
    assert await execute_ci(ctx) == "waiting"
    assert len(harness.turns) == 2


@pytest.mark.unit
async def test_oversized_ci_evidence_asks_instead_of_partial_pass(graph_case: GraphCase) -> None:
    from lgcw.github.port import CiEvidenceLimitError

    ctx, harness, head = await published(graph_case)
    graph_case.github.fail_after(
        "runs_for_sha", 1, CiEvidenceLimitError("CI run observation limit")
    )
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_evidence_limit"
    assert len(harness.turns) == 1 and not graph_case.github.rerun_requests


@pytest.mark.unit
@pytest.mark.parametrize("override", [{"run_attempt": 2}, {"head_branch": "foreign"}])
async def test_rerun_rechecks_run_identity_after_intent(
    graph_case: GraphCase, override: dict[str, object]
) -> None:
    from lgcw.ledger.markers import parse_markers
    from tests.graph.test_ci_wait import script_failure

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head, infrastructure=True)

    def changed(comment: IssueComment) -> None:
        if any(marker.kind == "rerun" for marker in parse_markers(comment.body)):
            graph_case.github.runs[head] = [
                graph_case.github.runs[head][0].model_copy(update=override)
            ]

    graph_case.github.after_comment = changed
    assert await execute_ci(ctx) == "waiting"
    assert not graph_case.github.rerun_requests
    assert markers(graph_case, "ask")[-1].code == "ci_run_changed"
    assert len(harness.turns) == 1
