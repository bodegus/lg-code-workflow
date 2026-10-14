"""Publication and owner-authorized restoration guards withstand concurrent local edits."""

from __future__ import annotations

import pytest

from lgcw.graph.context import RunContext
from lgcw.ledger.markers import parse_markers
from lgcw.models.github import IssueComment
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import EditingHarness, execute, markers, output, setup
from tests.unit.git.helpers import checked


async def dirty_candidate(case: GraphCase) -> tuple[RunContext, EditingHarness, str]:
    """Retain a candidate, dirty its tracked content and obtain the exact owner question."""
    ctx, harness = await setup(case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    case.workspace.crash_after = "commit_all"
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    candidate = case.workspace.commits[-1]
    (harness.root / "app.py").write_text("owner saw these bytes\n")
    assert await execute(ctx) == "waiting"
    assert markers(case, "ask")[-1].code == "workspace_changed"
    return ctx, harness, candidate


@pytest.mark.unit
async def test_publish_passes_audited_sha_when_head_moves_at_push_port(
    graph_case: GraphCase,
) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])

    async def moved() -> None:
        await checked(harness.root, "commit", "--allow-empty", "-m", "foreign local commit")

    graph_case.workspace.before_push = moved
    assert await execute(ctx) == "waiting"
    audited = graph_case.workspace.commits[-1]
    assert graph_case.workspace.pushes[-1] == audited
    assert (await ctx.github.get_pr(ctx.issue_ref.repo, 100)).head_sha == audited
    assert await graph_case.workspace.head_sha() != audited
    assert len(harness.turns) == 1


@pytest.mark.unit
async def test_restore_refuses_untracked_owner_work(graph_case: GraphCase) -> None:
    ctx, harness, _ = await dirty_candidate(graph_case)
    untracked = harness.root / "owner-note.txt"
    untracked.write_text("preserve these owner bytes\n")
    # Freeze the owner-visible proposal including the new untracked file.
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    assert not graph_case.workspace.restores and len(graph_case.workspace.pushes) == 1
    assert untracked.read_text() == "preserve these owner bytes\n"
    # The changed question must be acknowledged before the adapter refusal is reached.
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "local_head_changed"
    assert not graph_case.workspace.restores and len(graph_case.workspace.pushes) == 1
    assert untracked.read_text() == "preserve these owner bytes\n"


@pytest.mark.unit
@pytest.mark.parametrize("after_intent", [False, True])
async def test_restore_content_is_bound_before_intent_and_before_reset(
    graph_case: GraphCase, after_intent: bool
) -> None:
    ctx, harness, candidate = await dirty_candidate(graph_case)
    changed = "owner never approved these bytes\n"

    def alter(comment: IssueComment) -> None:
        if any(
            marker.kind == "publish" and getattr(marker, "phase", None) == "reset_intent"
            for marker in parse_markers(comment.body)
        ):
            graph_case.github.after_comment = None
            (harness.root / "app.py").write_text(changed)

    if after_intent:
        graph_case.github.after_comment = alter
    else:
        (harness.root / "app.py").write_text(changed)
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "workspace_changed"
    assert not graph_case.workspace.restores and len(graph_case.workspace.pushes) == 1
    assert await graph_case.workspace.head_sha() == candidate
    assert (harness.root / "app.py").read_text() == changed


@pytest.mark.unit
@pytest.mark.parametrize("after_intent", [False, True])
async def test_copied_owned_trailers_do_not_adopt_a_merge_commit(
    graph_case: GraphCase, after_intent: bool
) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    if after_intent:
        graph_case.workspace.crash_after = "commit_all"
    else:

        def stop_after_gate(comment: IssueComment) -> None:
            if any(
                marker.kind == "gate" and getattr(marker, "phase", None) == "complete"
                for marker in parse_markers(comment.body)
            ):
                graph_case.github.after_comment = None
                raise InjectedCrash("gate receipt lost before publication intent")

        graph_case.github.after_comment = stop_after_gate
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    parent = markers(graph_case, "push")[-1].head_sha
    if after_intent:
        candidate = graph_case.workspace.commits[-1]
    else:
        from lgcw.ledger.markers import fingerprint

        operation = fingerprint("publish", markers(graph_case, "build")[-1].operation_id)
        new_candidate = await graph_case.workspace.commit_all(
            "copied metadata",
            {
                "LGCW-Issue": f"{ctx.issue_ref.repo}#{ctx.issue_ref.number}",
                "LGCW-Operation": operation,
                "LGCW-Parent": parent,
            },
        )
        assert new_candidate is not None
        candidate = new_candidate
    tree = await checked(harness.root, "rev-parse", candidate + "^{tree}")
    message = await graph_case.workspace.commit_message(candidate)
    merge = await checked(
        harness.root, "commit-tree", tree, "-p", parent, "-p", candidate, "-m", message
    )
    await checked(harness.root, "reset", "--hard", merge)
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "local_head_changed"
    assert len(graph_case.workspace.pushes) == 1
    assert await graph_case.workspace.head_sha() == merge
