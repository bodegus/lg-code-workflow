"""Compiled build/gate/publish graph over fake services and a real local git origin."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import Runtime
from pydantic import BaseModel

from lgcw.graph.build_graph import STEPS, NodeFn
from lgcw.graph.context import RunContext
from lgcw.graph.nodes import DEFAULT_NODES
from lgcw.graph.nodes.build import build
from lgcw.graph.nodes.gate import gate
from lgcw.graph.nodes.publish import publish
from lgcw.graph.runner import run_issue
from lgcw.harness.errors import (
    HarnessAuthError,
    HarnessError,
    HarnessQuotaError,
    HarnessSessionLostError,
)
from lgcw.ledger.markers import parse_markers
from lgcw.models.base import Step
from lgcw.models.handoff import BuildHandoff, FileNote
from lgcw.models.harness import SessionRef, TurnInput, TurnOutcome, Usage
from lgcw.models.state import RunOutcome, RunState
from tests.fakes.harness import FakeHarness
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.unit.git.helpers import checked
from tests.unit.harness.cases import handoff


class EditingHarness(FakeHarness):
    """Simulate agent file edits at the HarnessPort boundary, before returning its claims."""

    def __init__(
        self, root: Path, edits: list[dict[str, str]], *, session_prefix: str = "fake"
    ) -> None:
        super().__init__(session_prefix=session_prefix)
        self.root = root
        self.edits = deque(edits)
        self.crash_after_turn = False
        self.after_turn: Callable[[], None] | None = None

    async def run_turn[M: BaseModel](
        self,
        session: SessionRef,
        turn: TurnInput,
        output: type[M],
        *,
        heartbeat: Callable[[], None],
    ) -> TurnOutcome[M]:
        if self.edits:
            for path, text in self.edits.popleft().items():
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        result = await super().run_turn(session, turn, output, heartbeat=heartbeat)
        if self.after_turn is not None:
            callback, self.after_turn = self.after_turn, None
            callback()
        if self.crash_after_turn:
            self.crash_after_turn = False
            raise InjectedCrash("paid turn response lost")
        return result


def output(*paths: str) -> BuildHandoff:
    """Return complete synthetic claims tied to the scripted edits."""
    return handoff().model_copy(
        update={
            "approach": "canonical version bump",
            "files": [FileNote(path=path, why="bounded fixture change") for path in paths],
        }
    )


async def setup(
    case: GraphCase,
    edits: list[dict[str, str]],
    answers: list[BaseModel | Exception],
    commands: tuple[str, ...] = (),
) -> tuple[RunContext, EditingHarness]:
    """Bootstrap with the existing real intake graph, then attach the scripted builder."""
    assert await case.run() == "waiting"
    harness = EditingHarness(case.workspace.prepares[-1].repo_dir, edits)
    harness.script("builder", answers)
    policy = case.ctx.repo.model_copy(update={"gate": commands, "protected_globs": ("AGENTS.md",)})
    config = case.ctx.config.model_copy(update={"repos": {policy.full_name: policy}})
    return case.ctx.model_copy(
        update={"repo": policy, "config": config, "harness": harness}
    ), harness


async def execute(ctx: RunContext) -> RunOutcome:
    """Run all implemented nodes and stop only at the explicit unit CI checkpoint."""

    async def checkpoint(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        runtime.context.log.event("unit_checkpoint", node="ci_wait")
        return {"next_step": "end", "outcome": "waiting"}

    mapping: dict[Step, NodeFn] = {step: checkpoint for step in STEPS if step != "end"}
    mapping.update(DEFAULT_NODES)
    mapping.update({"build": build, "gate": gate, "publish": publish})
    return await run_issue(ctx, nodes=mapping)


def markers(case: GraphCase, kind: str) -> list[Any]:
    """Read actual authenticated fixture comments rather than a local graph counter."""
    return [
        marker
        for comments in case.github.comments.values()
        for comment in comments
        for marker in parse_markers(comment.body)
        if marker.kind == kind
    ]


@pytest.mark.unit
async def test_happy_build_gate_publish(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 1
    assert len(markers(graph_case, "session")) == 1
    pushes = [marker for marker in markers(graph_case, "push") if marker.source == "build"]
    assert len(pushes) == 1 and len(graph_case.workspace.pushes) == 2
    document = await graph_case.github.get_pr_document(ctx.issue_ref.repo, 100)
    assert "canonical version bump" in document.body
    message = await graph_case.workspace.commit_message(pushes[0].head_sha)
    assert "LGCW-Issue:" in message and "LGCW-Operation:" in message
    writes = {"create_issue_comment", "create_draft_pr", "update_pr_body", "set_labels"}
    effects = [call for call in graph_case.github.calls if call[0] in writes]
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 2
    assert len(markers(graph_case, "push")) == 2
    assert effects == [call for call in graph_case.github.calls if call[0] in writes]


@pytest.mark.unit
async def test_gate_failure_then_fix(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "VERSION = 'broken'\n"}, {"app.py": "VERSION = '0.1.1'\n"}],
        [output("app.py"), output("app.py")],
        ("grep -q 0.1.1 app.py || { echo gate-tail-fixture; exit 1; }",),
    )
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 2
    assert "gate-tail-fixture" in harness.turns[1][1].text
    assert "release 0.1.1" in harness.turns[1][1].text
    assert harness.turns[0][0] == harness.turns[1][0]
    assert len(graph_case.workspace.pushes) == 2


@pytest.mark.unit
async def test_same_gate_failure_twice_restarts_then_asks(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "bad\n"}] * 3,
        [output("app.py")] * 3,
        ("echo repeat-gate-fixture; exit 1",),
    )
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 3
    sessions = markers(graph_case, "session")
    assert len(sessions) == 2 and sessions[-1].reason == "fresh_restart"
    assert markers(graph_case, "ask")[-1].code in {"builder_restart_limit", "gate_fix_limit"}
    assert len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_no_changes_counts_as_failure(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{}, {}, {}], [output()] * 3)
    assert await execute(ctx) == "waiting"
    assert 1 < len(harness.turns) <= 3
    assert markers(graph_case, "ask") and len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_protected_path_asks(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case, [{"AGENTS.md": "unrequested change\n"}], [output("AGENTS.md")]
    )
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "protected_path"
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_handoff_blocked_asks_with_question(graph_case: GraphCase) -> None:
    value = output().model_copy(update={"status": "blocked", "open_questions": ["Which version?"]})
    ctx, _ = await setup(graph_case, [{}], [value])
    assert await execute(ctx) == "waiting"
    assert "Which version?" in graph_case.github.comments[(ctx.issue_ref.repo, 100)][-1].body
    assert len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_auth_error_asks_without_push(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{}], [HarnessAuthError("dedicated login expired")])
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "harness_auth"
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_context_ratio_restarts_builder(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "VERSION = 'broken'\n"}, {"app.py": "VERSION = '0.1.1'\n"}],
        [output("app.py"), output("app.py")],
        ("grep -q 0.1.1 app.py",),
    )
    harness.usage_script.append(
        Usage(
            input_tokens=700,
            cached_input_tokens=0,
            output_tokens=1,
            reasoning_output_tokens=0,
            context_window=1000,
            context_input_tokens=700,
        )
    )
    assert await execute(ctx) == "waiting"
    assert harness.turns[0][0] != harness.turns[1][0]
    assert markers(graph_case, "session")[-1].reason == "fresh_restart"


@pytest.mark.unit
async def test_publish_once_across_crash(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    graph_case.workspace.crash_after = "push"
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    assert len(graph_case.workspace.pushes) == 2
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.pushes) == 2 and len(harness.turns) == 1
    assert len([m for m in markers(graph_case, "push") if m.source == "build"]) == 1
    assert (
        await checked(graph_case.origin.bare, "rev-parse", "lgcw/issue-1")
        == await ctx.workspace.head_sha()
    )


@pytest.mark.unit
async def test_pr_body_contains_atomic_publish_receipt(graph_case: GraphCase) -> None:
    ctx, _ = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    assert await execute(ctx) == "waiting"
    document = await ctx.github.get_pr_document(ctx.issue_ref.repo, 100)
    marker = parse_markers(document.body)[0]
    assert marker.kind == "run"
    assert marker.body_step == "publish"
    assert marker.body_head_sha == document.head_sha
    assert marker.body_operation_id == markers(graph_case, "publish")[-1].operation_id


@pytest.mark.unit
@pytest.mark.parametrize("boundary", list(range(1, 10)))
async def test_recovery_at_every_pr_comment_boundary(graph_case: GraphCase, boundary: int) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    graph_case.github.fail_after(
        "create_issue_comment", boundary, InjectedCrash("comment receipt lost")
    )
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    before_turns = len(harness.turns)
    assert await execute(ctx) == "waiting"
    expected_turns = 1 if boundary == 1 else before_turns
    assert len(harness.turns) == expected_turns
    if boundary in {2, 4}:
        assert markers(graph_case, "ask")[-1].code in {"build_unknown", "gate_unknown"}
        assert len(graph_case.workspace.pushes) == 1
    else:
        assert len(graph_case.workspace.pushes) == 2
        assert len(graph_case.workspace.commits) == 1
        assert len([m for m in markers(graph_case, "push") if m.source != "initial"]) == 1


@pytest.mark.unit
async def test_commit_response_lost_is_recovered_without_another_commit(
    graph_case: GraphCase,
) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    graph_case.workspace.crash_after = "commit_all"
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    assert len(graph_case.workspace.commits) == 1 and len(graph_case.workspace.pushes) == 1
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.commits) == 1 and len(graph_case.workspace.pushes) == 2
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_unknown_gate_never_reexecutes_without_owner(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "VERSION = '0.1.1'\n"}],
        [output("app.py")],
        ("printf gate-ran > receipt.txt",),
    )
    graph_case.workspace.crash_after = "run_commands"
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    runs = len(graph_case.workspace.command_runs)
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "gate_unknown"
    assert len(graph_case.workspace.command_runs) == runs
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_changed_bytes_after_gate_never_publish(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    graph_case.github.fail_after("create_issue_comment", 5, InjectedCrash("gate receipt lost"))
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    # Same path and same line/byte counts, different content: a numstat-only guard misses it.
    (harness.root / "app.py").write_text("VERSION = '0.1.2'\n")
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "workspace_changed"
    assert len(graph_case.workspace.pushes) == 1 and len(harness.turns) == 1


@pytest.mark.unit
async def test_commit_time_byte_race_cannot_bypass_gate(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "VERSION = '0.1.1'\n"}],
        [output("app.py")],
        ("grep -q 0.1.1 app.py",),
    )
    graph_case.workspace.commit_edits = {"app.py": "VERSION = '0.1.2'\n"}
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.pushes) == 1
    assert markers(graph_case, "ask")[-1].code == "workspace_changed"
    assert len(harness.turns) == 1


@pytest.mark.unit
@pytest.mark.parametrize("source", ["ci", "review"])
async def test_gate_fix_preserves_ci_or_review_publication_count(
    graph_case: GraphCase, source: str
) -> None:
    from lgcw.graph.nodes.common import observe
    from lgcw.ledger.markers import render_marker
    from lgcw.models.ledger import CiMarker, FeedbackMarker, FindingMarker, ReviewMarker
    from lgcw.models.state import Feedback
    from tests.unit.graph.cases import thread
    from tests.unit.harness.cases import finding

    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    assert await execute(ctx) == "waiting"
    parent = await ctx.workspace.head_sha()
    ci = CiMarker(
        head_sha=parent,
        status="failure" if source == "ci" else "success",
        klass="change" if source == "ci" else None,
        action="fix" if source == "ci" else "proceed_note",
        fingerprint="ci-fixture" if source == "ci" else None,
    )
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, render_marker(ci))
    if source == "review":
        await ctx.github.create_issue_comment(
            ctx.issue_ref.repo,
            100,
            render_marker(
                ReviewMarker(
                    head_sha=parent,
                    level="standard",
                    round=1,
                    lenses=("general",),
                    blocking=1,
                    nonblocking=0,
                    review_id=None,
                )
            ),
        )
        graph_case.github.threads[(ctx.issue_ref.repo, 100)] = [
            thread(FindingMarker(id="F-1", priority=1, lens="general", head_sha=parent))
        ]
    feedback = Feedback.model_validate(
        {
            "source": source,
            "summary": "fix current version",
            "data": "target 0.1.2",
            "fingerprint": source + "-fixture",
        }
    )
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo,
        100,
        render_marker(
            FeedbackMarker(
                head_sha=parent,
                feedback=feedback,
                findings=(finding(harness.root),) if source == "review" else (),
            )
        ),
    )
    harness.edits.extend([{"app.py": "VERSION = 'bad'\n"}, {"app.py": "VERSION = '0.1.2'\n"}])
    harness.script("builder", [output("app.py"), output("app.py")])
    policy = ctx.repo.model_copy(update={"gate": ("grep -q 0.1.2 app.py",)})
    ctx = ctx.model_copy(
        update={
            "repo": policy,
            "config": ctx.config.model_copy(update={"repos": {policy.full_name: policy}}),
        }
    )
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "push")[-1].source == source + "_fix"
    observed = await observe(ctx, await ctx.github.get_pr(ctx.issue_ref.repo, 100))
    counts = observed.ledger.counts()
    assert (counts.ci_fix_rounds if source == "ci" else counts.review_fix_rounds) == 1
    assert counts.gate_fix_rounds == 1
    assert len(harness.turns) == 3


@pytest.mark.unit
async def test_unknown_paid_result_requires_explicit_owner_retry(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    harness.crash_after_turn = True
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    assert len(harness.turns) == 1
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "build_unknown"
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 1
    harness.script("builder", [output("app.py")])
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 2 and len(graph_case.workspace.pushes) == 2
    assert len(markers(graph_case, "command_done")) == 1
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 2


@pytest.mark.unit
async def test_unmaterialized_session_marker_uses_one_fresh_builder(graph_case: GraphCase) -> None:
    ctx, original = await setup(graph_case, [], [])
    graph_case.github.fail_after("create_issue_comment", 1, InjectedCrash("session receipt lost"))
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    assert not original.turns
    restarted = EditingHarness(
        original.root, [{"app.py": "VERSION = '0.1.1'\n"}], session_prefix="new-process"
    )
    restarted.script("builder", [output("app.py")])
    ctx = ctx.model_copy(update={"harness": restarted})
    assert await execute(ctx) == "waiting"
    sessions = markers(graph_case, "session")
    assert len(sessions) == 2 and sessions[-1].cause == "session_lost"
    assert len(restarted.turns) == 1 and len(graph_case.workspace.pushes) == 2
    assert "issue" in restarted.turns[0][1].text and "release 0.1.1" in restarted.turns[0][1].text


@pytest.mark.unit
async def test_distinct_gate_failures_and_one_owner_grant_are_bounded(
    graph_case: GraphCase,
) -> None:
    commands = ("grep -q fixed app.py || { cat app.py; exit 1; }",)
    ctx, harness = await setup(
        graph_case,
        [{"app.py": value + "\n"} for value in ("alpha", "beta", "gamma")],
        [output("app.py")] * 3,
        commands,
    )
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "gate_fix_limit"
    assert len(harness.turns) == 3 and len(markers(graph_case, "session")) == 1
    harness.edits.append({"app.py": "fixed\n"})
    harness.script("builder", [output("app.py")])
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 4 and len(graph_case.workspace.pushes) == 2
    assert "gamma" in harness.turns[-1][1].text
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 4


@pytest.mark.unit
async def test_repeated_context_cause_asks_after_one_restart(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "alpha\n"}, {"app.py": "beta\n"}],
        [output("app.py")] * 2,
        ("cat app.py; exit 1",),
    )
    harness.usage = Usage(
        input_tokens=700,
        cached_input_tokens=0,
        output_tokens=1,
        reasoning_output_tokens=0,
        context_window=1000,
        context_input_tokens=700,
    )
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "builder_restart_limit"
    assert len(harness.turns) == 2 and len(markers(graph_case, "session")) == 2
    assert len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_owner_closes_after_build_no_gate_or_push(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    key = (ctx.issue_ref.repo, 100)

    def close() -> None:
        graph_case.github.prs[key] = graph_case.github.prs[key].model_copy(
            update={"state": "CLOSED"}
        )

    harness.after_turn = close
    assert await execute(ctx) == "closed"
    assert not markers(graph_case, "ask")
    assert len(graph_case.workspace.pushes) == 1 and not graph_case.workspace.command_runs[-1:]


@pytest.mark.unit
async def test_changed_bytes_after_build_receipt_never_reach_gate(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])

    def mutate(comment: Any) -> None:
        if any(m.kind == "build" and m.phase == "complete" for m in parse_markers(comment.body)):
            (harness.root / "app.py").write_text("VERSION = '0.1.2'\n")

    graph_case.github.after_comment = mutate
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "workspace_changed"
    assert not graph_case.workspace.command_runs
    assert len(graph_case.workspace.pushes) == 1 and len(harness.turns) == 1


@pytest.mark.unit
async def test_successful_gate_that_changes_content_requires_new_build(
    graph_case: GraphCase,
) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "VERSION = '0.1.1'\n"}] * 3,
        [output("app.py")] * 3,
        ("printf 'changed during gate\\n' > app.py",),
    )
    assert await execute(ctx) == "waiting"
    gates = [m for m in markers(graph_case, "gate") if m.phase == "complete"]
    assert gates and all(m.code == 0 and m.feedback is not None for m in gates)
    assert all("content" in m.feedback.summary for m in gates)
    assert len(graph_case.workspace.pushes) == 1
    assert len(harness.turns) > 1


@pytest.mark.unit
async def test_unknown_gate_requires_owner_retry_and_runs_only_once_more(
    graph_case: GraphCase,
) -> None:
    ctx, harness = await setup(
        graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")], ("true",)
    )
    graph_case.workspace.crash_after = "run_commands"
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "gate_unknown"
    assert len(graph_case.workspace.command_runs) == 1
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.command_runs) == 2 and len(harness.turns) == 1
    assert len(graph_case.workspace.pushes) == 2
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.command_runs) == 2


@pytest.mark.unit
async def test_quota_without_reset_asks_explicitly_and_never_pushes(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{}], [HarnessQuotaError()])
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "harness_quota"
    assert (
        "reset time unavailable" in graph_case.github.comments[(ctx.issue_ref.repo, 100)][-1].body
    )
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 1
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_busy_session_error_never_starts_fresh_builder(graph_case: GraphCase) -> None:
    ctx, harness = await setup(graph_case, [{}], [HarnessError("turn still in progress")])
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "harness_error"
    assert len(markers(graph_case, "session")) == 1 and len(harness.turns) == 1
    assert len(graph_case.workspace.pushes) == 1


@pytest.mark.unit
async def test_session_lost_twice_asks_after_one_fresh_builder(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{}, {}],
        [HarnessSessionLostError("lost"), HarnessSessionLostError("lost again")],
    )
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "harness_session_lost"
    assert len(markers(graph_case, "session")) == 2 and len(harness.turns) == 2
    assert len(graph_case.workspace.pushes) == 1
