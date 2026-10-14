"""Second-round reviewer reproductions against the complete compiled graph."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import markers, output
from tests.graph.test_ci_wait import execute_ci, published, script_failure


@pytest.mark.unit
@pytest.mark.parametrize("sequence", ["\x1bP", "\x1b^", "\x1b_", "\x1bX", "\x1b]52;c;"])
async def test_unterminated_sequence_preserves_following_failure_everywhere(
    graph_case: GraphCase, sequence: str
) -> None:
    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.github.logs[1] = "FAILED known_flaky\n" + sequence + "\nFAILED real_regression"
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    feedback = markers(graph_case, "feedback")[-1].feedback.data
    assert "FAILED real_regression" in feedback
    assert "FAILED real_regression" in harness.turns[1][1].text
    files = list(Path(ctx.log.run_dir).rglob("*-full.log"))
    assert len(files) == 1
    assert "FAILED real_regression" in files[0].read_text()
    assert "\x1b" not in files[0].read_text()


@pytest.mark.unit
@pytest.mark.parametrize("source", ["run-associations", "open-pr"])
async def test_other_pr_sharing_head_never_supplies_success(
    graph_case: GraphCase, source: str
) -> None:
    from lgcw.models.github import RunPullRequest
    from tests.unit.ci.cases import job, run

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    if source == "run-associations":
        graph_case.github.runs[head].append(
            run(identifier=2, head=head).model_copy(
                update={
                    "pull_requests": (100, 101),
                    "pr_associations": (
                        RunPullRequest(number=100, base_ref="main"),
                        RunPullRequest(number=101, base_ref="release"),
                    ),
                }
            )
        )
        graph_case.github.jobs[2] = [job(run_id=2, conclusion="success")]
    else:
        key = (ctx.issue_ref.repo, 100)
        competing = graph_case.github.prs[key].model_copy(
            update={"number": 101, "base_ref": "release"}
        )

        def add_competing(method: str) -> None:
            if method == "runs_for_sha":
                graph_case.github.prs[(ctx.issue_ref.repo, 101)] = competing

        graph_case.github.after_call = add_competing
        graph_case.github.runs[head] = [run(head=head)]
        graph_case.github.jobs[1] = [job(conclusion="success")]
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_ownership_ambiguous"
    assert not markers(graph_case, "ci") and not graph_case.github.rerun_requests
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_cancelled_timeout_reruns_then_succeeds(graph_case: GraphCase) -> None:
    from tests.unit.ci.cases import job, run

    ctx, harness, head = await published(graph_case)
    timeout = job(conclusion="cancelled", annotations=("exceeded the maximum execution time",))
    graph_case.github.base_jobs[(ctx.issue_ref.repo, "CI", "main")] = [timeout]
    graph_case.github.script_runs(
        head,
        [
            (0, [run(head=head, conclusion="cancelled")], [timeout]),
            (15, [run(head=head, attempt=2)], [job(conclusion="success", attempt=2)]),
        ],
    )
    assert await execute_ci(ctx) == "waiting"
    assert sum(graph_case.github.rerun_requests.values()) == 1
    assert markers(graph_case, "ci")[-1].status == "success"
    assert not markers(graph_case, "ask") and len(harness.turns) == 1


@pytest.mark.unit
@pytest.mark.parametrize("boundary", ["observation", "dispatch"])
async def test_remote_branch_moves_independently_of_pr(
    graph_case: GraphCase, boundary: str
) -> None:
    from lgcw.ledger.markers import parse_markers

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head, infrastructure=True)
    graph_case.github.pr_head_overrides[(ctx.issue_ref.repo, 100)] = head

    def move() -> None:
        graph_case.github.branch_heads[(ctx.issue_ref.repo, "lgcw/issue-1")] = "f" * 40

    def after_call(method: str) -> None:
        if boundary == "observation" and method == "runs_for_sha":
            move()

    def after_comment(comment: object) -> None:
        from lgcw.models.github import IssueComment

        assert isinstance(comment, IssueComment)
        if boundary == "dispatch" and any(m.kind == "rerun" for m in parse_markers(comment.body)):
            move()

    graph_case.github.after_call = after_call
    graph_case.github.after_comment = after_comment
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "head_moved"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 1
    if boundary == "observation":
        assert not markers(graph_case, "ci")


@pytest.mark.unit
@pytest.mark.parametrize("boundary", ["observation", "dispatch"])
async def test_pr_closes_during_observation_or_dispatch(
    graph_case: GraphCase, boundary: str
) -> None:
    from lgcw.ledger.markers import parse_markers
    from lgcw.models.github import IssueComment

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head, infrastructure=True)

    def close() -> None:
        key = (ctx.issue_ref.repo, 100)
        graph_case.github.prs[key] = graph_case.github.prs[key].model_copy(
            update={"state": "CLOSED"}
        )

    def after_call(method: str) -> None:
        if boundary == "observation" and method == "latest_base_jobs":
            close()

    def after_comment(comment: IssueComment) -> None:
        if boundary == "dispatch" and any(m.kind == "rerun" for m in parse_markers(comment.body)):
            close()

    graph_case.github.after_call = after_call
    graph_case.github.after_comment = after_comment
    assert await execute_ci(ctx) == "closed"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 1
    if boundary == "observation":
        assert not markers(graph_case, "ci")


@pytest.mark.unit
async def test_run_change_before_intent_never_strands_rerun_intent(graph_case: GraphCase) -> None:
    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head, infrastructure=True)

    def changed(method: str) -> None:
        if method == "latest_base_jobs":
            graph_case.github.runs[head] = [
                graph_case.github.runs[head][0].model_copy(update={"conclusion": "success"})
            ]

    graph_case.github.after_call = changed
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_run_changed"
    assert not markers(graph_case, "rerun") and not graph_case.github.rerun_requests
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_aggregate_job_cap_never_evaluates_partial_evidence(graph_case: GraphCase) -> None:
    from tests.unit.ci.cases import job, run

    ctx, harness, head = await published(graph_case)
    graph_case.github.runs[head] = [run(head=head), run(identifier=2, workflow="Other", head=head)]
    graph_case.github.jobs[1] = [job(identifier=i) for i in range(100)]
    graph_case.github.jobs[2] = [
        job(identifier=100 + i, run_id=2, workflow="Other") for i in range(101)
    ]
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_evidence_limit"
    assert not markers(graph_case, "ci") and len(harness.turns) == 1


@pytest.mark.unit
async def test_recorded_rerun_cannot_resume_against_another_attempt(graph_case: GraphCase) -> None:
    from lgcw.ledger.markers import render_marker
    from lgcw.models.ledger import CiMarker
    from tests.unit.ci.cases import run, runner_job

    ctx, harness, head = await published(graph_case)
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo,
        100,
        render_marker(
            CiMarker(
                head_sha=head,
                status="failure",
                klass="infra",
                action="rerun",
                fingerprint=None,
                run_id=1,
                run_attempt=1,
            )
        ),
    )
    graph_case.github.runs[head] = [run(head=head, attempt=2, conclusion="failure")]
    graph_case.github.jobs[1] = [
        runner_job(annotations=("runner lost communication",)).model_copy(update={"run_attempt": 2})
    ]
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 2
    assert [m for m in markers(graph_case, "ci") if m.head_sha == head][-1].action == "fix"


@pytest.mark.unit
@pytest.mark.parametrize("boundary", ["before-intent", "after-intent"])
async def test_competing_pr_appears_before_dispatch(graph_case: GraphCase, boundary: str) -> None:
    from lgcw.ledger.markers import parse_markers
    from lgcw.models.github import IssueComment

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head, infrastructure=True)

    def add() -> None:
        original = graph_case.github.prs[(ctx.issue_ref.repo, 100)]
        graph_case.github.prs[(ctx.issue_ref.repo, 101)] = original.model_copy(
            update={"number": 101, "base_ref": "release"}
        )

    def after_call(method: str) -> None:
        if boundary == "before-intent" and method == "latest_base_jobs":
            add()

    def after_comment(comment: IssueComment) -> None:
        if boundary == "after-intent" and any(
            m.kind == "rerun" for m in parse_markers(comment.body)
        ):
            add()

    graph_case.github.after_call = after_call
    graph_case.github.after_comment = after_comment
    assert await execute_ci(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "ci_ownership_ambiguous"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 1
    assert len(markers(graph_case, "rerun")) == (0 if boundary == "before-intent" else 1)


@pytest.mark.unit
@pytest.mark.parametrize("path", [".github", None, ".github/x"])
async def test_printed_annotation_reaches_builder_with_regression_log(
    graph_case: GraphCase, path: str | None
) -> None:
    from tests.unit.ci.cases import job

    ctx, harness, head = await published(graph_case)
    script_failure(graph_case, head)
    graph_case.github.jobs[1] = [
        job(annotations=("The runner lost communication",)).model_copy(
            update={"annotation_paths": (path,)}
        )
    ]
    graph_case.github.logs[1] = "FAILED actual_regression"
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    assert not graph_case.github.rerun_requests and len(harness.turns) == 2
    assert "actual_regression" in harness.turns[1][1].text


@pytest.mark.unit
async def test_failed_rerun_with_new_class_reaches_builder(graph_case: GraphCase) -> None:
    from tests.unit.ci.cases import run, runner_job

    ctx, harness, head = await published(graph_case)
    graph_case.github.script_runs(
        head,
        [
            (
                0,
                [run(head=head, conclusion="failure")],
                [runner_job(annotations=("runner lost communication",))],
            ),
            (
                15,
                [run(head=head, attempt=2, conclusion="failure")],
                [runner_job(annotations=("ENOSPC",)).model_copy(update={"run_attempt": 2})],
            ),
        ],
    )
    graph_case.github.logs[1] = "Error: actual-rerun-regression"
    harness.edits.append({"app.py": "VERSION = '0.1.2'\n"})
    harness.script("builder", [output("app.py")])
    assert await execute_ci(ctx) == "waiting"
    assert sum(graph_case.github.rerun_requests.values()) == 1 and len(harness.turns) == 2
    assert "actual-rerun-regression" in harness.turns[1][1].text
    assert [m for m in markers(graph_case, "ci") if m.head_sha == head][-1].action == "fix"
