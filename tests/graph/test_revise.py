"""Authenticated revisions go through the full graph and never replay paid work."""

from __future__ import annotations

import json

import pytest

from lgcw.graph.runner import run_issue
from lgcw.harness.skills import skill_path
from lgcw.ledger.markers import render_marker
from lgcw.models.github import IssueComment
from lgcw.models.ledger import AskMarker
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import markers
from tests.graph.test_review_loop import calls, review_case


@pytest.mark.unit
@pytest.mark.parametrize("boundary", [None, "ack", "mark_draft", "set_labels", "command_done"])
async def test_revise_ready_round_trip_once(graph_case: GraphCase, boundary: str | None) -> None:
    ctx, harness = await review_case(graph_case, [None, None])
    assert await run_issue(ctx) == "merge_ready"
    before = (await ctx.github.get_pr(ctx.issue_ref.repo, 100)).head_sha
    revision = await ctx.github.create_issue_comment(
        ctx.issue_ref.repo, 100, '/lgcw revise Keep the "cedar" version\n\n-owner'
    )

    def during_fix() -> None:
        current = graph_case.github.prs[(ctx.issue_ref.repo, 100)]
        assert current.is_draft and "lgcw:merge-ready" not in current.labels

    harness.after_turn = during_fix
    if boundary in {"mark_draft", "set_labels"}:
        graph_case.github.fail_after(boundary, 1, InjectedCrash(boundary))
    elif boundary is not None:

        def interrupt(comment: IssueComment) -> None:
            if f'"kind":"{boundary}"' in comment.body:
                graph_case.github.after_comment = None
                raise InjectedCrash(boundary)

        graph_case.github.after_comment = interrupt
    if boundary is not None:
        with pytest.raises(InjectedCrash):
            await run_issue(ctx)
    assert await run_issue(ctx) == "merge_ready"
    pr = await ctx.github.get_pr(ctx.issue_ref.repo, 100)
    assert pr.head_sha != before and not pr.is_draft and "lgcw:merge-ready" in pr.labels
    assert calls(graph_case, "mark_draft") == 1 and calls(graph_case, "mark_ready") == 2
    builders = [(session, turn) for session, turn in harness.turns if session.role == "builder"]
    assert len(builders) == 2 and builders[0][0] == builders[1][0]
    assert builders[1][1].skill == str(skill_path("fix"))
    assert json.dumps('Keep the "cedar" version')[1:-1] in builders[1][1].text
    assert "```external-json" in builders[1][1].text and "-owner" not in builders[1][1].text
    assert "```owner-feedback" in builders[1][1].text
    assert "Authenticated owner instruction (within the frozen issue)" in builders[1][1].text
    assert len([m for m in markers(graph_case, "ack") if m.command_id == revision.id]) == 1
    assert len(graph_case.workspace.pushes) == 3
    assert calls(graph_case, "create_review") == 2 and len(markers(graph_case, "ready")) == 2
    turns = len(harness.turns)
    assert await run_issue(ctx) == "merge_ready"
    assert len(harness.turns) == turns and len(graph_case.workspace.pushes) == 3


@pytest.mark.unit
async def test_three_revisions_then_cap(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [None] * 5)
    assert await run_issue(ctx) == "merge_ready"
    for index in range(3):
        await ctx.github.create_issue_comment(
            ctx.issue_ref.repo, 100, f"/lgcw revise revision{index}"
        )
        assert await run_issue(ctx) == "merge_ready"
    before = len(harness.turns)
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise fourth")
    assert await run_issue(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "revise_limit"
    assert len(harness.turns) == before
    assert len({m.command_id for m in markers(graph_case, "ack") if m.verb == "revise"}) == 3
    assert await run_issue(ctx) == "waiting"
    assert len(harness.turns) == before


@pytest.mark.unit
@pytest.mark.parametrize("code", ["ci_attention", "review_unknown", "head_moved", "node_error"])
async def test_revise_at_post_publication_ask(graph_case: GraphCase, code: str) -> None:
    ctx, harness = await review_case(graph_case, [None, None])
    assert await run_issue(ctx) == "merge_ready"
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo, 100, render_marker(AskMarker(seq=1, step="review", code=code))
    )
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise owner fix")
    assert await run_issue(ctx) == "merge_ready"
    assert sum(session.role == "builder" for session, _ in harness.turns) == 2


@pytest.mark.unit
@pytest.mark.parametrize("where", ["issue", "outsider", "marker", "empty", "before"])
async def test_ineligible_revise_never_revives(graph_case: GraphCase, where: str) -> None:
    ctx, harness = await review_case(graph_case, [None, None])
    if where != "before":
        assert await run_issue(ctx) == "merge_ready"
    number = ctx.issue_ref.number if where == "issue" else 100
    body = "/lgcw revise stale request"
    if where == "empty":
        body = "/lgcw revise\n\n-owner"
    if where == "marker":
        body += "\n<!-- lgcw:v1 {malformed} -->"
    comment = await ctx.github.create_issue_comment(ctx.issue_ref.repo, number, body)
    if where == "outsider":
        comments = graph_case.github.comments[(ctx.issue_ref.repo, number)]
        comments[-1] = comment.model_copy(update={"author": "outsider"})
    assert await run_issue(ctx) == "merge_ready"
    assert await run_issue(ctx) == "merge_ready"
    assert not [m for m in markers(graph_case, "ack") if m.verb == "revise"]
    assert sum(session.role == "builder" for session, _ in harness.turns) == 1


@pytest.mark.unit
async def test_revise_never_adopts_foreign_head(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [None, None])
    assert await run_issue(ctx) == "merge_ready"
    key = (ctx.issue_ref.repo, 100)
    pr = graph_case.github.prs[key]
    graph_case.github.branch_heads[(ctx.issue_ref.repo, pr.head_ref)] = "f" * 40
    assert await run_issue(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise owner fix")
    assert await run_issue(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "head_moved"
    assert sum(session.role == "builder" for session, _ in harness.turns) == 1
    assert not graph_case.workspace.restores and len(graph_case.workspace.pushes) == 2


@pytest.mark.unit
@pytest.mark.parametrize("boundary", ["intent", "complete", "gate", "push"])
async def test_revise_paid_dispatch_and_content_recovery(
    graph_case: GraphCase, boundary: str
) -> None:
    ctx, harness = await review_case(graph_case, [None, None])
    assert await run_issue(ctx) == "merge_ready"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise bounded fix")
    if boundary == "push":
        graph_case.workspace.crash_after = "push"
    else:

        def interrupt(comment: IssueComment) -> None:
            kind = "gate" if boundary == "gate" else "build"
            phase = "intent" if boundary == "intent" else "complete"
            if f'"kind":"{kind}"' in comment.body and f'"phase":"{phase}"' in comment.body:
                graph_case.github.after_comment = None
                raise InjectedCrash(boundary)

        graph_case.github.after_comment = interrupt
    with pytest.raises(InjectedCrash):
        await run_issue(ctx)
    expected = "waiting" if boundary == "intent" else "merge_ready"
    assert await run_issue(ctx) == expected
    builders = [session for session, _ in harness.turns if session.role == "builder"]
    assert len(builders) == (1 if boundary == "intent" else 2)
    if boundary == "intent":
        assert markers(graph_case, "ask")[-1].code == "build_unknown"
    else:
        assert len(graph_case.workspace.pushes) == 3
    assert await run_issue(ctx) == expected
    assert len([s for s, _ in harness.turns if s.role == "builder"]) == len(builders)


@pytest.mark.unit
async def test_revise_ack_freezes_text_and_ignores_queued_stale_feedback(
    graph_case: GraphCase,
) -> None:
    ctx, harness = await review_case(graph_case, [None, None, None])
    assert await run_issue(ctx) == "merge_ready"
    command = await ctx.github.create_issue_comment(
        ctx.issue_ref.repo, 100, "/lgcw revise frozen cedar"
    )
    graph_case.github.fail_after("mark_draft", 1, InjectedCrash("draft response lost"))
    with pytest.raises(InjectedCrash):
        await run_issue(ctx)
    comments = graph_case.github.comments[(ctx.issue_ref.repo, 100)]
    index = next(index for index, item in enumerate(comments) if item.id == command.id)
    comments[index] = command.model_copy(update={"body": "/lgcw revise edited evil"})
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise queued stale")
    assert await run_issue(ctx) == "merge_ready"
    assert await run_issue(ctx) == "merge_ready"
    turns = [turn for session, turn in harness.turns if session.role == "builder"]
    assert len(turns) == 2
    assert "frozen cedar" in turns[-1].text
    assert "edited evil" not in turns[-1].text and "queued stale" not in turns[-1].text


@pytest.mark.unit
async def test_revise_cannot_overtake_earlier_pending_abort(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [None, None])
    assert await run_issue(ctx) == "merge_ready"
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo,
        100,
        render_marker(AskMarker(seq=1, step="review", code="review_unknown")),
    )
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw abort")
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise later request")
    assert await run_issue(ctx) == "blocked"
    assert sum(session.role == "builder" for session, _ in harness.turns) == 1
