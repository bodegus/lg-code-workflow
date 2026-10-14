"""Third-round crash, owner revocation and scope-parser regressions."""

from __future__ import annotations

import json
from typing import Any

import pytest
from langgraph.runtime import Runtime

from lgcw.graph.build_graph import STEPS, NodeFn
from lgcw.graph.context import RunContext
from lgcw.graph.nodes import DEFAULT_NODES
from lgcw.graph.runner import run_issue
from lgcw.ledger.markers import parse_markers
from lgcw.models.base import Step
from lgcw.models.github import IssueComment
from lgcw.models.ledger import GateMarker
from lgcw.models.state import RunState
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import execute, markers, output, setup


@pytest.mark.unit
async def test_approve_gate_failure_receipt_crash_does_not_loop(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"AGENTS.md": "A\n"}, {"AGENTS.md": "B\n"}],
        [output("AGENTS.md")] * 2,
        ("exit 1",),
    )
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer approve")

    def crash(comment: IssueComment) -> None:
        if any(
            isinstance(m, GateMarker) and m.phase == "complete" for m in parse_markers(comment.body)
        ):
            graph_case.github.after_comment = None
            raise InjectedCrash("measured gate response lost")

    graph_case.github.after_comment = crash
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 2 and len(graph_case.workspace.command_runs) == 1
    assert len(graph_case.workspace.pushes) == 1
    events = [
        json.loads(line) for line in (ctx.log.run_dir / "events.jsonl").read_text().splitlines()
    ]
    assert sum(event["kind"] == "node_start" and event["node"] == "gate" for event in events) == 1


@pytest.mark.unit
async def test_no_progress_graph_publishes_recoverable_node_error(graph_case: GraphCase) -> None:
    assert await graph_case.run() == "waiting"

    async def spin(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        return {
            "pr": await runtime.context.github.get_pr(runtime.context.issue_ref.repo, 100),
            "next_step": "build",
        }

    nodes: dict[Step, NodeFn] = {step: spin for step in STEPS if step != "end"}
    nodes["ask"] = DEFAULT_NODES["ask"]
    assert await run_issue(graph_case.ctx, nodes=nodes) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "node_error"
    assert len([method for method, _ in graph_case.github.calls if method == "get_pr"]) < 20
    await graph_case.ctx.github.create_issue_comment(
        graph_case.ctx.issue_ref.repo, 100, "/lgcw abort"
    )
    assert await graph_case.run() == "blocked"


@pytest.mark.unit
@pytest.mark.parametrize("timing", ["before-run", "during-gate", "before-push"])
@pytest.mark.parametrize("command", ["/lgcw answer No. Revert protected changes.", "/lgcw abort"])
async def test_later_owner_command_revokes_acked_approval(
    graph_case: GraphCase, timing: str, command: str
) -> None:
    from lgcw.models.ledger import AckMarker, PublishMarker

    ctx, harness = await setup(graph_case, [{"AGENTS.md": "A\n"}], [output("AGENTS.md")])
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer approve")

    def post_later() -> None:
        graph_case.github.comments[(ctx.issue_ref.repo, 100)].append(
            IssueComment(
                id=10000, author=ctx.workflow_login, body=command, created_at=ctx.clock.now()
            )
        )

    def changed(comment: IssueComment) -> None:
        parsed = parse_markers(comment.body)
        if timing == "before-run" and any(isinstance(m, AckMarker) for m in parsed):
            graph_case.github.after_comment = None
            raise InjectedCrash("approval ack response lost")
        if timing == "before-push" and any(
            isinstance(m, PublishMarker) and m.phase == "committed" for m in parsed
        ):
            graph_case.github.after_comment = None
            post_later()

    graph_case.github.after_comment = changed
    if timing == "before-run":
        with pytest.raises(InjectedCrash):
            await execute(ctx)
        post_later()
    if timing == "during-gate":

        async def after_commands() -> None:
            post_later()

        graph_case.workspace.after_commands = after_commands
    assert await execute(ctx) == ("blocked" if command == "/lgcw abort" else "waiting")
    assert len(graph_case.workspace.pushes) == 1 and len(harness.turns) == 1
    assert any(m.command_id == 10000 for m in markers(graph_case, "ack"))
    if command != "/lgcw abort":
        assert markers(graph_case, "ask")[-1].code == "protected_path"


@pytest.mark.unit
async def test_restored_parent_rebuild_prompt_discards_reset_claims(graph_case: GraphCase) -> None:
    from tests.graph.test_build_review_r2 import payload

    ctx, harness = await setup(
        graph_case, [{"app.py": "A\n"}, {"app.py": "B\n"}], [output("app.py")] * 2
    )
    graph_case.workspace.commit_edits = {"app.py": "not-gated\n"}
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    assert "Rebuild from the restored published parent" in harness.turns[-1][1].text
    assert payload(harness.turns[-1][1].text)["previous_handoff"] is None
    assert len(harness.turns) == 2 and len(graph_case.workspace.pushes) == 2


@pytest.mark.unit
@pytest.mark.parametrize("command", ["/lgcw answer approve but not this", "/lgcw retry approve"])
async def test_approval_must_be_exact_answer_not_prefix_or_retry(
    graph_case: GraphCase, command: str
) -> None:
    ctx, harness = await setup(
        graph_case, [{"AGENTS.md": "A\n"}, {"AGENTS.md": "A\n"}], [output("AGENTS.md")] * 2
    )
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, command)
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.pushes) == 1 and len(harness.turns) == 2
    assert markers(graph_case, "ask")[-1].code == "protected_path"


@pytest.mark.unit
async def test_approval_ack_route_must_match_question(graph_case: GraphCase) -> None:
    from lgcw.ledger.markers import render_marker
    from lgcw.models.ledger import AckMarker, Command

    ctx, harness = await setup(graph_case, [{"AGENTS.md": "A\n"}], [output("AGENTS.md")])
    assert await execute(ctx) == "waiting"
    question = markers(graph_case, "ask")[-1]
    comment = await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer approve")
    ack = AckMarker(
        seq=question.seq,
        command_id=comment.id,
        verb="answer",
        step="gate",
        command_snapshot=Command(
            verb="answer", text="approve", comment_id=comment.id, author=ctx.workflow_login
        ),
        adopt=None,
    )
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, render_marker(ack))
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.pushes) == 1 and len(harness.turns) == 1
    assert markers(graph_case, "ask")[-1].code == "protected_path"


@pytest.mark.unit
async def test_existing_gate_receipt_finishes_restored_command(graph_case: GraphCase) -> None:
    from lgcw.graph.nodes.common import observe
    from lgcw.graph.nodes.gate import gate
    from lgcw.models.issue import IntakeResult
    from lgcw.models.ledger import AckMarker, RunMarker

    ctx, _ = await setup(graph_case, [{"AGENTS.md": "A\n"}], [output("AGENTS.md")], ("exit 1",))
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer approve")

    def crash(comment: IssueComment) -> None:
        if any(
            isinstance(m, GateMarker) and m.phase == "complete" for m in parse_markers(comment.body)
        ):
            graph_case.github.after_comment = None
            raise InjectedCrash("result retained before command done")

    graph_case.github.after_comment = crash
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    pr = await ctx.github.get_pr(ctx.issue_ref.repo, 100)
    observations = await observe(ctx, pr)
    run = observations.ledger.latest("run")
    assert run is not None and isinstance(run.marker, RunMarker)
    ack = observations.ledger.latest("ack")
    assert ack is not None and isinstance(ack.marker, AckMarker)
    state = RunState(
        issue_ref=ctx.issue_ref,
        issue=run.marker.snapshot,
        intake=IntakeResult(status="ok", acceptance_criteria=run.marker.criteria, reason=None),
        pr=pr,
        branch=pr.head_ref,
        ledger=observations.ledger,
        owner_command=ack.marker.command_snapshot,
    )
    delta = await gate(state, Runtime(context=ctx))
    assert delta["owner_command"] is None and delta["next_step"] == "build"
    assert any(m.command_id == ack.marker.command_id for m in markers(graph_case, "command_done"))
    assert len(graph_case.workspace.command_runs) == 1
