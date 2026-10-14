"""Crash recovery and final-readiness invariants on the compiled prototype."""

from __future__ import annotations

import pytest

from lgcw.graph.runner import run_issue
from lgcw.models.github import IssueComment
from lgcw.models.ledger import ReviewMarker
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import markers
from tests.graph.test_review_loop import calls, review_case


@pytest.mark.unit
@pytest.mark.parametrize("method,n", [("update_pr_body", 2), ("mark_ready", 1), ("set_labels", 1)])
async def test_readiness_effects_recover_once(graph_case: GraphCase, method: str, n: int) -> None:
    ctx, harness = await review_case(graph_case, [None])
    graph_case.github.fail_after(method, n, InjectedCrash("readiness effect response lost"))
    with pytest.raises(InjectedCrash):
        await run_issue(ctx)
    assert await run_issue(ctx) == "merge_ready"
    assert calls(graph_case, "mark_ready") == 1
    assert calls(graph_case, "update_pr_body") == 2
    assert calls(graph_case, "create_review") == 1
    assert len(markers(graph_case, "ready")) == 1 and len(harness.turns) == 2


@pytest.mark.unit
async def test_ready_receipt_response_loss_finishes_without_effects(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [None])

    def interrupted(comment: IssueComment) -> None:
        if '"kind":"ready"' in comment.body:
            graph_case.github.after_comment = None
            raise InjectedCrash("ready response lost")

    graph_case.github.after_comment = interrupted
    with pytest.raises(InjectedCrash):
        await run_issue(ctx)
    effects = list(graph_case.github.calls)
    assert await run_issue(ctx) == "merge_ready"
    writes = {"update_pr_body", "mark_ready", "create_review", "create_issue_comment", "set_labels"}
    assert [call for call in effects if call[0] in writes] == [
        call for call in graph_case.github.calls if call[0] in writes
    ]
    assert len(harness.turns) == 2


@pytest.mark.unit
@pytest.mark.parametrize("change", ["head", "conflict", "dirty", "ci", "policy", "issue"])
async def test_readiness_rechecks_current_evidence(graph_case: GraphCase, change: str) -> None:
    ctx, harness = await review_case(graph_case, [None])

    def change_after_review(method: str) -> None:
        if method != "create_review":
            return
        graph_case.github.after_call = None
        key = (ctx.issue_ref.repo, 100)
        pr = graph_case.github.prs[key]
        if change == "head":
            graph_case.github.branch_heads[(ctx.issue_ref.repo, pr.head_ref)] = "f" * 40
            graph_case.github.prs[key] = pr.model_copy(update={"head_sha": "f" * 40})
        elif change == "conflict":
            graph_case.github.prs[key] = pr.model_copy(update={"mergeable": "CONFLICTING"})
        elif change == "dirty":
            (harness.root / "app.py").write_text("VERSION = 'foreign'\n")
        elif change == "ci":
            graph_case.github.jobs[1] = [
                graph_case.github.jobs[1][0].model_copy(update={"conclusion": "failure"})
            ]
        elif change == "policy":
            graph_case.github.required_contexts[(ctx.issue_ref.repo, "main")] = ("security",)
        elif change == "issue":
            issue_key = (ctx.issue_ref.repo, ctx.issue_ref.number)
            issue = graph_case.github.issues[issue_key]
            graph_case.github.issues[issue_key] = issue.model_copy(
                update={"body": issue.body + "\nEdited later."}
            )

    graph_case.github.after_call = change_after_review
    assert await run_issue(ctx) == ("merge_ready" if change == "issue" else "waiting")
    assert len(harness.turns) == 2
    if change == "issue":
        assert (
            "Issue changed after pickup" in graph_case.github.pr_bodies[(ctx.issue_ref.repo, 100)]
        )
    else:
        assert calls(graph_case, "mark_ready") == 0 and not markers(graph_case, "ready")


@pytest.mark.unit
async def test_readiness_rechecks_head_after_ready_api(graph_case: GraphCase) -> None:
    ctx, _ = await review_case(graph_case, [None])

    def changed(method: str) -> None:
        if method == "mark_ready":
            graph_case.github.after_call = None
            key = (ctx.issue_ref.repo, 100)
            graph_case.github.branch_heads[
                (ctx.issue_ref.repo, graph_case.github.prs[key].head_ref)
            ] = "f" * 40
            graph_case.github.prs[key] = graph_case.github.prs[key].model_copy(
                update={"head_sha": "f" * 40}
            )

    graph_case.github.after_call = changed
    assert await run_issue(ctx) == "waiting"
    assert not markers(graph_case, "ready")


@pytest.mark.unit
def test_review_receipt_binds_blocker_counts() -> None:
    from pydantic import ValidationError

    from lgcw.models.review import GateResult

    with pytest.raises(ValidationError, match="counts"):
        ReviewMarker(
            head_sha="a" * 40,
            level="light",
            round=1,
            lenses=("general",),
            blocking=1,
            nonblocking=0,
            review_id=None,
            result=GateResult(blocking=(), nonblocking=(), dropped=()),
        )
