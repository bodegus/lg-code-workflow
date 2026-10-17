"""Revision intent survives new command IDs and never changes approval authority."""

from __future__ import annotations

import re
from collections import deque

import pytest

from lgcw.graph.runner import run_issue
from lgcw.harness.errors import HarnessAuthError, HarnessQuotaError, HarnessSessionLostError
from lgcw.models.github import IssueComment
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import markers, output
from tests.graph.test_review_loop import calls, review_case
from tests.unit.git.helpers import checked


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure", ["intent", "dispatch", "quota", "auth", "session", "head_moved"]
)
async def test_active_revision_survives_retry(graph_case: GraphCase, failure: str) -> None:
    ctx, harness = await review_case(graph_case, [None, None, None])
    assert await run_issue(ctx) == "merge_ready"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise durable cedar")
    if failure in {"quota", "auth", "session"}:
        error = (
            HarnessQuotaError()
            if failure == "quota"
            else HarnessAuthError("expired")
            if failure == "auth"
            else HarnessSessionLostError("lost")
        )
        for _ in range(2 if failure == "session" else 1):
            harness._scripts["builder"].appendleft(error)
            harness.edits.appendleft({})
        assert await run_issue(ctx) == "waiting"
    elif failure == "head_moved":
        graph_case.github.fail_after("mark_draft", 1, InjectedCrash("draft response lost"))
        with pytest.raises(InjectedCrash):
            await run_issue(ctx)
        # Simulate a move to a prior workflow-owned head, not an arbitrary foreign SHA.
        pr = graph_case.github.prs[(ctx.issue_ref.repo, 100)]
        owned = graph_case.workspace.pushes[0]
        await checked(graph_case.origin.bare, "update-ref", f"refs/heads/{pr.head_ref}", owned)
        graph_case.github.branch_heads[(ctx.issue_ref.repo, pr.head_ref)] = owned
        assert await run_issue(ctx) == "waiting"
        assert markers(graph_case, "ask")[-1].code == "head_moved"
    else:
        if failure == "dispatch":
            harness.crash_after_turn = True
        else:

            def crash(comment: IssueComment) -> None:
                if '"kind":"build"' in comment.body and '"phase":"intent"' in comment.body:
                    graph_case.github.after_comment = None
                    raise InjectedCrash("intent response lost")

            graph_case.github.after_comment = crash
        with pytest.raises(InjectedCrash):
            await run_issue(ctx)
        assert await run_issue(ctx) == "waiting"
        assert markers(graph_case, "ask")[-1].code == "build_unknown"
    # A fresh queued edit prevents a no-change result after a lost paid dispatch/push.
    harness.edits = deque([{"app.py": "VERSION = '0.1.8'\n"}])

    def while_fixing() -> None:
        pr = graph_case.github.prs[(ctx.issue_ref.repo, 100)]
        assert pr.is_draft and "lgcw:merge-ready" not in pr.labels

    harness.after_turn = while_fixing
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await run_issue(ctx) == "merge_ready"
    builders = [turn for session, turn in harness.turns if session.role == "builder"]
    assert "durable cedar" in builders[-1].text and "```owner-feedback" in builders[-1].text
    skill = "build" if failure == "session" else "fix"
    assert builders[-1].skill.endswith(f"/{skill}/SKILL.md")
    if failure == "session":
        sessions = [session for session, _ in harness.turns if session.role == "builder"]
        assert sessions[-1] != sessions[0]
        assert '"previous_handoff"' in builders[-1].text
    turns = len(harness.turns)
    assert await run_issue(ctx) == "merge_ready" and len(harness.turns) == turns


@pytest.mark.unit
@pytest.mark.parametrize("where", ["pr", "issue"])
async def test_revise_after_protected_approval(graph_case: GraphCase, where: str) -> None:
    ctx, harness = await review_case(graph_case, [None, None, None])
    # Publish a normal first round, then request a protected change in a revision.
    assert await run_issue(ctx) == "merge_ready"
    harness.edits = deque([{"AGENTS.md": "approved content\n"}])
    harness._scripts["builder"].clear()
    harness.script("builder", [output("AGENTS.md"), output("app.py")])
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise protected source")
    assert await run_issue(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "protected_path"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer approve")
    if where == "issue":

        def during_gate(comment: IssueComment) -> None:
            if '"kind":"gate"' in comment.body and '"phase":"intent"' in comment.body:
                graph_case.github.after_comment = None
                graph_case.github.comments[(ctx.issue_ref.repo, ctx.issue_ref.number)].append(
                    IssueComment(
                        id=comment.id + 1,
                        author=ctx.workflow_login,
                        body="/lgcw revise ignored",
                        created_at=ctx.clock.now(),
                    )
                )

        graph_case.github.after_comment = during_gate
    else:
        assert await run_issue(ctx) == "merge_ready"
        harness.edits = deque([{"app.py": "VERSION = '0.1.9'\n"}])
        await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise app only")
    result = await run_issue(ctx)
    assert result == "merge_ready"
    assert not [m for m in markers(graph_case, "ask") if m.code == "node_error"]
    assert await checked(harness.root, "show", "HEAD:AGENTS.md") == "approved content"
    assert sum(session.role == "builder" for session, _ in harness.turns) == (
        3 if where == "pr" else 2
    )


@pytest.mark.unit
async def test_revise_ignored_at_prepublication_protected_ask(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [None])
    harness.edits = deque([{"AGENTS.md": "proposal\n"}])
    harness._scripts["builder"].clear()
    harness.script("builder", [output("AGENTS.md")])
    assert await run_issue(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw revise too early")
    assert await run_issue(ctx) == "waiting"
    assert not markers(graph_case, "ack") and len(harness.turns) == 1
    assert calls(graph_case, "mark_draft") == 0


@pytest.mark.unit
async def test_revision_text_redacted_and_fence_longer_than_payload(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [None, None])
    assert await run_issue(ctx) == "merge_ready"
    token = "ghp_" + "x" * 28
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo, 100, f"/lgcw revise keep ```` fenced {token}"
    )
    assert await run_issue(ctx) == "merge_ready"
    ack = [m for m in markers(graph_case, "ack") if m.verb == "revise"][-1]
    assert token not in ack.model_dump_json() and "[REDACTED]" in ack.model_dump_json()
    text = [turn.text for session, turn in harness.turns if session.role == "builder"][-1]
    assert token not in text and "[REDACTED]" in text
    opening = re.search(r"(?m)^(`+)owner-feedback$", text)
    assert opening is not None and len(opening.group(1)) > 4
