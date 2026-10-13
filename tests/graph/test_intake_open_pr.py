"""Draft PR and owner-command crash contracts through the compiled graph."""

from __future__ import annotations

import pytest

from lgcw.ledger.markers import parse_markers
from lgcw.models.ledger import Marker, RunMarker
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.unit.git.helpers import checked


def markers(case: GraphCase, kind: str) -> list[Marker]:
    """Inspect actual comment bodies independently of node-local state."""
    return [
        marker
        for comments in case.github.comments.values()
        for comment in comments
        for marker in parse_markers(comment.body)
        if marker.kind == kind
    ]


def writes(case: GraphCase) -> int:
    """Count service mutations, excluding read-only reconciliation."""
    return sum(
        name in {"create_issue_comment", "create_draft_pr", "set_labels", "update_pr_body"}
        for name, _ in case.github.calls
    )


@pytest.mark.unit
async def test_incomplete_issue_asks_on_issue(graph_case: GraphCase) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(
        update={"body": "please bump version"}
    )
    assert await case.run() == "waiting"
    assert len(markers(case, "ask")) == 1 and not case.github.prs
    assert "lgcw:waiting" in case.github.issues[key].labels


@pytest.mark.unit
async def test_rerun_while_waiting_posts_nothing(graph_case: GraphCase) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(
        update={"body": "missing criteria"}
    )
    await case.run()
    assert len(markers(case, "ask")) == 1 and not case.github.prs
    before = writes(case)
    assert await case.run() == "waiting" and writes(case) == before


@pytest.mark.unit
async def test_owner_answer_resumes_to_open_pr(graph_case: GraphCase) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(
        update={"body": "missing criteria"}
    )
    await case.run()
    await case.github.create_issue_comment(*key, "/lgcw answer Release 0.1.1 and preserve the CLI")
    await case.run()
    assert len(markers(case, "ack")) == 1 and len(case.github.prs) == 1
    assert next(iter(case.github.prs.values())).is_draft


@pytest.mark.unit
@pytest.mark.parametrize("effect", ["commit_empty", "push", "create_draft_pr", "set_labels"])
async def test_open_pr_once_across_crash(graph_case: GraphCase, effect: str) -> None:
    case = graph_case
    if effect in {"commit_empty", "push"}:
        case.workspace.crash_after = effect
    else:
        case.github.fail_after(effect, 1, InjectedCrash(effect))
    with pytest.raises(InjectedCrash):
        await case.run()
    await case.run()
    assert len(case.github.prs) == 1 and len(case.workspace.pushes) == 1
    assert sum(name == "create_draft_pr" for name, _ in case.github.calls) == 1
    assert len(case.workspace.empty_commits) == 1
    assert len(markers(case, "push")) == 1
    assert "[skip ci]" in await checked(
        case.origin.bare, "log", "lgcw/issue-1", "-1", "--format=%B"
    )
    assert await checked(case.origin.bare, "rev-parse", "main") == case.origin.base


@pytest.mark.unit
async def test_foreign_author_issue_blocked(graph_case: GraphCase) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(update={"author": "foreign"})
    assert await case.run() == "blocked"
    assert not case.github.prs and not case.workspace.pushes
    assert len(markers(case, "blocked")) == 1


@pytest.mark.unit
async def test_abort_blocks(graph_case: GraphCase) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(update={"body": "missing"})
    await case.run()
    await case.github.create_issue_comment(*key, "/lgcw abort Stop this run")
    assert await case.run() == "blocked" and not case.github.prs
    before = writes(case)
    assert await case.run() == "blocked" and writes(case) == before


@pytest.mark.unit
async def test_setup_unknown_result_asks_without_executing_twice(graph_case: GraphCase) -> None:
    case = graph_case
    policy = case.ctx.repo.model_copy(update={"setup": ("echo prepared",)})
    config = case.ctx.config.model_copy(update={"repos": {policy.full_name: policy}})
    ctx = case.ctx.model_copy(update={"repo": policy, "config": config})
    case = case.model_copy(update={"ctx": ctx})
    case.workspace.crash_after = "run_commands"
    with pytest.raises(InjectedCrash):
        await case.run()
    assert await case.run() == "waiting"
    assert len(case.workspace.command_runs) == 1 and not case.workspace.pushes
    assert len(markers(case, "ask")) == 1


@pytest.mark.unit
async def test_ack_crash_resumes_frozen_command_without_second_ack(graph_case: GraphCase) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(
        update={"body": "missing criteria"}
    )
    await case.run()
    await case.github.create_issue_comment(*key, "/lgcw answer Release 0.1.1")
    case.github.fail_after("create_issue_comment", 1, InjectedCrash("ack"))
    with pytest.raises(InjectedCrash):
        await case.run()
    await case.run()
    assert len(markers(case, "ack")) == 1 and len(case.github.prs) == 1


@pytest.mark.unit
async def test_snapshot_survives_issue_edit(graph_case: GraphCase) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(
        update={"body": "original without criteria"}
    )
    await case.run()
    case.github.issues[key] = case.github.issues[key].model_copy(
        update={"body": "edited body must not replace snapshot"}
    )
    await case.github.create_issue_comment(*key, "/lgcw answer Release 0.1.1")
    await case.run()
    run = markers(case, "run")[-1]
    assert isinstance(run, RunMarker) and run.snapshot is not None
    assert run.snapshot.body == "original without criteria"


@pytest.mark.unit
@pytest.mark.parametrize("comment_number", range(1, 7))
async def test_each_bootstrap_comment_recovers_without_repetition(
    graph_case: GraphCase, comment_number: int
) -> None:
    case = graph_case
    case.github.fail_after("create_issue_comment", comment_number, InjectedCrash("receipt"))
    with pytest.raises(InjectedCrash):
        await case.run()
    await case.run()
    assert (
        len(case.github.prs) == len(case.workspace.pushes) == len(case.workspace.empty_commits) == 1
    )
    assert len(markers(case, "intake")) == len(markers(case, "push")) == 1
    before = writes(case)
    await case.run()
    assert writes(case) == before


@pytest.mark.unit
async def test_closed_pr_is_recovered_by_linked_receipt(graph_case: GraphCase) -> None:
    case = graph_case
    await case.run()
    key = next(iter(case.github.prs))
    case.github.prs[key] = case.github.prs[key].model_copy(update={"state": "CLOSED"})
    before = writes(case)
    assert await case.run() == "closed" and writes(case) == before


@pytest.mark.unit
@pytest.mark.parametrize("foreign", [False, True])
async def test_terminal_label_crash_repairs_without_duplicate_comment(
    graph_case: GraphCase, foreign: bool
) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    update = {"author": "foreign"} if foreign else {"body": "missing"}
    case.github.issues[key] = case.github.issues[key].model_copy(update=update)
    case.github.fail_after("set_labels", 1, InjectedCrash("labels"))
    with pytest.raises(InjectedCrash):
        await case.run()
    before = writes(case)
    assert await case.run() == ("blocked" if foreign else "waiting")
    assert writes(case) == before


@pytest.mark.unit
async def test_setup_retry_can_fail_then_wait_without_replay(graph_case: GraphCase) -> None:
    case = graph_case
    policy = case.ctx.repo.model_copy(update={"setup": ("exit 3",)})
    config = case.ctx.config.model_copy(update={"repos": {policy.full_name: policy}})
    case = case.model_copy(
        update={"ctx": case.ctx.model_copy(update={"repo": policy, "config": config})}
    )
    assert await case.run() == "waiting"
    await case.github.create_issue_comment(
        case.ctx.issue_ref.repo, case.ctx.issue_ref.number, "/lgcw retry"
    )
    assert await case.run() == "waiting" and len(case.workspace.command_runs) == 2
    before = writes(case)
    assert await case.run() == "waiting"
    assert writes(case) == before and len(case.workspace.command_runs) == 2


@pytest.mark.unit
@pytest.mark.parametrize("comment_number", range(1, 9))
async def test_answered_intake_recovers_every_comment_without_new_intake(
    graph_case: GraphCase, comment_number: int
) -> None:
    case = graph_case
    key = (case.ctx.issue_ref.repo, case.ctx.issue_ref.number)
    case.github.issues[key] = case.github.issues[key].model_copy(update={"body": "missing"})
    await case.run()
    await case.github.create_issue_comment(*key, "/lgcw answer Release 0.1.1")
    case.github.fail_after("create_issue_comment", comment_number, InjectedCrash("receipt"))
    with pytest.raises(InjectedCrash):
        await case.run()
    await case.run()
    assert len(markers(case, "intake")) == 2
    assert len(markers(case, "ack")) == len(markers(case, "push")) == 1
    assert (
        len(case.workspace.empty_commits) == len(case.workspace.pushes) == len(case.github.prs) == 1
    )


@pytest.mark.unit
async def test_new_question_prevents_old_ack_continuation_replay(graph_case: GraphCase) -> None:
    import json

    case = graph_case
    policy = case.ctx.repo.model_copy(update={"setup": ("exit 3",)})
    config = case.ctx.config.model_copy(update={"repos": {policy.full_name: policy}})
    case = case.model_copy(
        update={"ctx": case.ctx.model_copy(update={"repo": policy, "config": config})}
    )
    await case.run()
    await case.github.create_issue_comment(
        case.ctx.issue_ref.repo, case.ctx.issue_ref.number, "/lgcw retry"
    )
    await case.run()
    events = case.ctx.log.run_dir / "events.jsonl"
    previous = len(events.read_text().splitlines())
    await case.run()
    new_events = [json.loads(line) for line in events.read_text().splitlines()[previous:]]
    # The fixed end terminator is registered outside _logged (build_graph.py).
    # Exactly reconcile may run while waiting: never replay open_pr or a paid continuation.
    assert [entry["node"] for entry in new_events if entry["kind"] == "node_start"] == ["reconcile"]


@pytest.mark.unit
async def test_context_never_serializes_code_token_capability(graph_case: GraphCase) -> None:
    assert "tokens" not in graph_case.ctx.model_dump()
    assert "tokens=" not in repr(graph_case.ctx)


@pytest.mark.unit
@pytest.mark.parametrize("crash", [None, 1, 2, 3])
async def test_human_head_adoption_is_exact_and_durable(
    graph_case: GraphCase, crash: int | None
) -> None:
    from lgcw.models.ledger import PushMarker

    case = graph_case
    await case.run()
    repo, number = next(iter(case.github.prs))
    branch = case.github.prs[(repo, number)].head_ref
    await checked(case.origin.seed, "fetch", "origin", branch)
    await checked(case.origin.seed, "checkout", "-b", branch, "FETCH_HEAD")
    (case.origin.seed / "owner.txt").write_text("owner work\n")
    await checked(case.origin.seed, "add", "-A")
    await checked(case.origin.seed, "commit", "-m", "owner addition")
    owner_head = await checked(case.origin.seed, "rev-parse", "HEAD")
    await checked(case.origin.seed, "push", "origin", branch)
    case.github.branch_heads[(repo, branch)] = owner_head
    assert await case.run() == "waiting"
    await case.github.create_issue_comment(repo, number, "/lgcw retry")
    if crash is not None:
        case.github.fail_after("create_issue_comment", crash, InjectedCrash("adoption"))
        with pytest.raises(InjectedCrash):
            await case.run()
    await case.run()
    adopted = [
        item
        for item in markers(case, "push")
        if isinstance(item, PushMarker) and item.source == "human"
    ]
    assert len(adopted) == 1 and adopted[0].head_sha == owner_head
    assert await case.workspace.head_sha() == owner_head
    assert await checked(case.origin.bare, "rev-parse", branch) == owner_head
    assert len(case.workspace.pushes) == 1
    before = writes(case)
    await case.run()
    assert writes(case) == before
