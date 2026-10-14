"""Minimal review workflow through the real compiled graph and local git."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel

from lgcw.graph.context import RunContext
from lgcw.graph.runner import run_issue
from lgcw.models.harness import SessionRef, TurnInput, TurnOutcome
from lgcw.models.review import CodeLocation, LineRange, ReviewFinding, ReviewVerdict
from tests.fakes.harness import FakeHarness
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import EditingHarness, markers, output, setup
from tests.unit.ci.cases import job, run


class ReviewHarness(EditingHarness):
    """Script fresh reviewer evidence without applying the next builder's file edits."""

    def __init__(
        self, root: Path, edits: list[dict[str, str]], priorities: list[int | None]
    ) -> None:
        super().__init__(root, edits)
        self.priorities = deque(priorities)

    async def run_turn[M: BaseModel](
        self,
        session: SessionRef,
        turn: TurnInput,
        output: type[M],
        *,
        heartbeat: Callable[[], None],
    ) -> TurnOutcome[M]:
        if session.role != "reviewer":
            return await super().run_turn(session, turn, output, heartbeat=heartbeat)
        priority = self.priorities.popleft()
        root = self.sessions[-1].cwd
        findings = (
            []
            if priority is None
            else [
                ReviewFinding(
                    title=f"[P{priority}] Preserve the expected version",
                    body="The updated version violates the specified compatibility contract.",
                    confidence_score=0.95,
                    priority=priority,
                    category="correctness",
                    code_location=CodeLocation(
                        absolute_file_path=str(root / "app.py"),
                        line_range=LineRange(start=1, end=1),
                    ),
                )
            ]
        )
        self.script(
            "reviewer",
            [
                ReviewVerdict(
                    findings=findings,
                    overall_correctness="patch is incorrect" if findings else "patch is correct",
                    overall_explanation="Synthetic evidence from the committed fixture diff.",
                    overall_confidence_score=0.95,
                )
            ],
        )
        return await FakeHarness.run_turn(self, session, turn, output, heartbeat=heartbeat)


async def review_case(
    case: GraphCase, priorities: list[int | None], *, level: str = "light"
) -> tuple[RunContext, ReviewHarness]:
    """Install actual build edits and exact-head passing CI at the fake service boundary."""
    edits = [{"app.py": f"VERSION = '0.1.{i + 1}'\n"} for i in range(len(priorities) + 1)]
    ctx, old = await setup(case, edits, [])
    harness = ReviewHarness(old.root, edits, priorities)
    harness.script("builder", [output("app.py")] * len(edits))
    key = (ctx.issue_ref.repo, 100)
    case.github.prs[key] = case.github.prs[key].model_copy(
        update={"labels": (f"lgcw:review-{level}",)}
    )

    def passing(head: str) -> None:
        case.github.runs[head] = [run(head=head)]
        case.github.jobs[1] = [job(conclusion="success")]

    case.workspace.after_push = passing
    return ctx.model_copy(update={"harness": harness}), harness


def calls(case: GraphCase, name: str) -> int:
    """Count actual recorded adapter effects."""
    return sum(method == name for method, _ in case.github.calls)


@pytest.mark.unit
async def test_level_none_goes_straight_to_merge_ready(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [], level="none")
    assert await run_issue(ctx) == "merge_ready"
    assert len(harness.turns) == 1
    assert calls(graph_case, "create_review") == 0
    assert calls(graph_case, "mark_ready") == 1


@pytest.mark.unit
async def test_light_clean_review_marks_ready_once(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [None])
    assert await run_issue(ctx) == "merge_ready"
    assert await run_issue(ctx) == "merge_ready"
    assert [session.role for session, _ in harness.turns] == ["builder", "reviewer"]
    reviewer = harness.sessions[-1]
    assert reviewer.sandbox == "read_only" and not reviewer.network
    assert calls(graph_case, "create_review") == calls(graph_case, "mark_ready") == 1
    assert len(markers(graph_case, "ready")) == 1
    pr = await ctx.github.get_pr(ctx.issue_ref.repo, 100)
    assert not pr.is_draft and "lgcw:merge-ready" in pr.labels and "lgcw:active" not in pr.labels
    review = next(args for method, args in graph_case.github.calls if method == "create_review")
    assert review["comments"] == ()


@pytest.mark.unit
async def test_blocking_finding_round_trip(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [1, None])
    assert await run_issue(ctx) == "merge_ready"
    turns = [session for session, _ in harness.turns]
    assert [session.role for session in turns] == ["builder", "reviewer", "builder", "reviewer"]
    assert turns[0] == turns[2] and turns[1] != turns[3]
    assert "Preserve the expected version" in harness.turns[2][1].text
    assert markers(graph_case, "push")[-1].source == "review_fix"
    assert calls(graph_case, "create_review") == 2 and calls(graph_case, "mark_ready") == 1
    assert not graph_case.github.threads


@pytest.mark.unit
async def test_round_cap_asks_then_retry_grants_one(graph_case: GraphCase) -> None:
    ctx, harness = await review_case(graph_case, [1, 1, 1])
    assert await run_issue(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "review_round_limit"
    assert sum(session.role == "reviewer" for session, _ in harness.turns) == 2
    assert await run_issue(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await run_issue(ctx) == "waiting"
    assert sum(session.role == "reviewer" for session, _ in harness.turns) == 3
    assert markers(graph_case, "ask")[-1].code == "review_round_limit"
    assert await run_issue(ctx) == "waiting"
    assert sum(session.role == "reviewer" for session, _ in harness.turns) == 3
    assert calls(graph_case, "mark_ready") == 0


@pytest.mark.unit
@pytest.mark.parametrize("level", ["standard", "deep"])
async def test_configured_levels_map_to_one_light_reviewer(
    graph_case: GraphCase, level: str
) -> None:
    ctx, harness = await review_case(graph_case, [2], level=level)
    assert await run_issue(ctx) == "merge_ready"
    assert [session.role for session, _ in harness.turns] == ["builder", "reviewer"]
    events = (ctx.log.run_dir / "events.jsonl").read_text()
    assert f'"configured":"{level}"' in events and '"executed":"light"' in events
    assert "configured " + level in graph_case.github.reviews[(ctx.issue_ref.repo, 100)][0].body


@pytest.mark.unit
async def test_submitted_review_lost_response_is_not_repeated(graph_case: GraphCase) -> None:
    from tests.fakes.workspace import InjectedCrash

    ctx, harness = await review_case(graph_case, [None])
    graph_case.github.fail_after("create_review", 1, InjectedCrash("review response lost"))
    with pytest.raises(InjectedCrash):
        await run_issue(ctx)
    assert await run_issue(ctx) == "merge_ready"
    assert len(harness.turns) == 2 and calls(graph_case, "create_review") == 1


@pytest.mark.unit
async def test_unknown_dispatch_asks_without_a_second_paid_turn(graph_case: GraphCase) -> None:
    from lgcw.models.github import IssueComment
    from tests.fakes.workspace import InjectedCrash

    ctx, harness = await review_case(graph_case, [None])

    def interrupted(comment: IssueComment) -> None:
        if '"kind":"session","role":"reviewer"' in comment.body:
            graph_case.github.after_comment = None
            raise InjectedCrash("review intent response lost")

    graph_case.github.after_comment = interrupted
    with pytest.raises(InjectedCrash):
        await run_issue(ctx)
    assert len(harness.turns) == 1
    assert await run_issue(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "review_unknown"
    assert len(harness.turns) == 1
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await run_issue(ctx) == "merge_ready"
    assert len(harness.turns) == 2


@pytest.mark.unit
async def test_committed_review_size_ignores_local_edits(graph_case: GraphCase) -> None:
    from lgcw.review.diffstat import parse_numstat
    from tests.graph.test_build_gate_publish import execute

    ctx, harness = await review_case(graph_case, [None])
    # One addition, preserving the base line: the assertion counts additions plus deletions.
    harness.edits = deque(
        [{"app.py": (harness.root / "app.py").read_text() + "NOTE = 'size fixture'\n"}]
    )
    assert await execute(ctx) == "waiting"
    head = (await ctx.github.get_pr(ctx.issue_ref.repo, 100)).head_sha
    (harness.root / "app.py").unlink()
    (harness.root / "foreign.txt").write_text("not in the published head\n")
    stats = parse_numstat(await ctx.workspace.commit_numstat(graph_case.origin.base, head), ())
    assert stats.paths == ("app.py",) and stats.changed_lines == 1


@pytest.mark.unit
async def test_fix_cannot_lower_prior_review_to_none(graph_case: GraphCase) -> None:
    ctx, old = await setup(graph_case, [], [])
    base_app = (old.root / "app.py").read_text()
    base_readme = ""  # The local origin has no README; the fix adds a documentation file.
    harness = ReviewHarness(
        old.root,
        [
            {"app.py": "VERSION = '0.1.1'\n"},
            {"app.py": base_app, "README.md": base_readme + "\nVersion note.\n"},
        ],
        [1, None],
    )
    harness.script("builder", [output("app.py"), output("app.py", "README.md")])

    def passing(head: str) -> None:
        graph_case.github.runs[head] = [run(head=head)]
        graph_case.github.jobs[1] = [job(conclusion="success")]

    graph_case.workspace.after_push = passing
    ctx = ctx.model_copy(update={"harness": harness})
    assert await run_issue(ctx) == "merge_ready"
    assert [session.role for session, _ in harness.turns] == [
        "builder",
        "reviewer",
        "builder",
        "reviewer",
    ]
