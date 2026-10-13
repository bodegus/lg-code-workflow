"""T13 review regressions exercise real node transitions and every ownership guard."""

from __future__ import annotations

import json
import shutil

import pytest

from lgcw.ledger.markers import render_marker
from lgcw.models.github import PrSnapshot
from lgcw.models.ledger import AskMarker, BootstrapMarker, IntakeMarker, RunMarker, SetupMarker
from tests.fakes.github import FakeGitHub
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_intake_open_pr import markers, writes
from tests.unit.git.helpers import checked


def issue_key(case: GraphCase) -> tuple[str, int]:
    """Return the fixture's original issue address."""
    return case.ctx.issue_ref.repo, case.ctx.issue_ref.number


def question_code(case: GraphCase) -> str:
    """Read the newest actual question marker without node-local state."""
    item = markers(case, "ask")[-1]
    assert isinstance(item, AskMarker)
    return item.code


async def move_remote(case: GraphCase) -> str:
    """Create a real owner commit on the issue branch and update the fake service view."""
    branch = f"lgcw/issue-{case.ctx.issue_ref.number}"
    current = await checked(case.origin.bare, "for-each-ref", f"refs/heads/{branch}")
    if current:
        await checked(case.origin.seed, "fetch", "origin", branch)
        await checked(case.origin.seed, "checkout", "-b", branch, "FETCH_HEAD")
    else:
        await checked(case.origin.seed, "checkout", "-b", branch)
    (case.origin.seed / "owner.txt").write_text("owner work\n")
    await checked(case.origin.seed, "add", "-A")
    await checked(case.origin.seed, "commit", "-m", "owner addition")
    head = await checked(case.origin.seed, "rev-parse", "HEAD")
    await checked(case.origin.seed, "push", "origin", branch)
    case.github.branch_heads[(case.ctx.issue_ref.repo, branch)] = head
    return head


@pytest.mark.unit
@pytest.mark.parametrize("verb", ["retry", "answer Scope is unchanged"])
@pytest.mark.parametrize("crash_ack", [False, True])
async def test_reconcile_error_continuation_finishes_once(
    graph_case: GraphCase, verb: str, crash_ack: bool
) -> None:
    case = graph_case
    case.github.fail_after("get_issue", 1, ValueError("synthetic read failure"))
    assert await case.run() == "waiting" and question_code(case) == "node_error"
    await case.github.create_issue_comment(*issue_key(case), f"/lgcw {verb}")
    if crash_ack:
        case.github.fail_after("create_issue_comment", 1, InjectedCrash("ack"))
        with pytest.raises(InjectedCrash):
            await case.run()
    assert await case.run() == "waiting"
    assert (
        len(case.github.prs) == len(markers(case, "ack")) == len(markers(case, "command_done")) == 1
    )
    events = [
        json.loads(line)
        for line in (case.ctx.log.run_dir / "events.jsonl").read_text().splitlines()
    ]
    assert (
        sum(event["kind"] == "node_start" and event["node"] == "reconcile" for event in events) <= 4
    )


@pytest.mark.unit
async def test_head_moved_answer_asks_again_and_abort_works(graph_case: GraphCase) -> None:
    case = graph_case
    await case.run()
    await move_remote(case)
    await case.run()
    number = next(iter(case.github.prs.values())).number
    await case.github.create_issue_comment(
        case.ctx.issue_ref.repo, number, "/lgcw answer Inspect again"
    )
    assert await case.run() == "waiting" and question_code(case) == "head_moved"
    assert len(markers(case, "command_done")) == 1
    await case.github.create_issue_comment(case.ctx.issue_ref.repo, number, "/lgcw abort")
    assert await case.run() == "blocked"


@pytest.mark.unit
async def test_failed_adoption_can_retry_then_abort(graph_case: GraphCase) -> None:
    case = graph_case
    await case.run()
    await move_remote(case)
    await case.run()
    number = next(iter(case.github.prs.values())).number
    assert case.workspace.prepares
    checkout = case.workspace.prepares[-1].repo_dir
    (checkout / "pending.txt").write_text("preserve local work")
    await case.github.create_issue_comment(case.ctx.issue_ref.repo, number, "/lgcw retry")
    assert await case.run() == "waiting" and question_code(case) == "node_error"
    await case.github.create_issue_comment(case.ctx.issue_ref.repo, number, "/lgcw retry")
    assert await case.run() == "waiting" and question_code(case) == "head_moved"
    await case.github.create_issue_comment(case.ctx.issue_ref.repo, number, "/lgcw abort")
    assert await case.run() == "blocked" and (checkout / "pending.txt").exists()


@pytest.mark.unit
async def test_no_pr_remote_change_retry_can_recheck_then_abort(graph_case: GraphCase) -> None:
    case = graph_case
    case.workspace.crash_after = "commit_empty"
    with pytest.raises(InjectedCrash):
        await case.run()
    await move_remote(case)
    assert await case.run() == "waiting" and question_code(case) == "head_moved"
    await case.github.create_issue_comment(*issue_key(case), "/lgcw retry")
    assert await case.run() == "waiting"
    await case.github.create_issue_comment(*issue_key(case), "/lgcw abort")
    assert await case.run() == "blocked"
    assert not case.workspace.pushes and not case.github.prs


@pytest.mark.unit
@pytest.mark.parametrize("state", ["CLOSED", "MERGED"])
async def test_crash_then_owner_closes_pr_never_recreates(
    graph_case: GraphCase, state: str
) -> None:
    case = graph_case
    case.github.fail_after("create_draft_pr", 1, InjectedCrash("created"))
    with pytest.raises(InjectedCrash):
        await case.run()
    key = next(iter(case.github.prs))
    case.github.prs[key] = case.github.prs[key].model_copy(update={"state": state})
    before = writes(case)
    assert await case.run() == "closed"
    assert writes(case) == before
    assert len(case.github.prs) == len(case.workspace.pushes) == 1
    assert sum(name == "create_draft_pr" for name, _ in case.github.calls) == 1


@pytest.mark.unit
async def test_lost_unpublished_clone_can_recheckpoint_once(graph_case: GraphCase) -> None:
    case = graph_case
    case.github.fail_after("create_issue_comment", 3, InjectedCrash("run intent"))
    with pytest.raises(InjectedCrash):
        await case.run()
    original = markers(case, "run")[-1]
    assert isinstance(original, RunMarker)
    assert case.workspace.prepares
    shutil.rmtree(case.workspace.prepares[-1].repo_dir)
    assert await case.run() == "waiting" and len(case.github.prs) == 1
    assert len(case.workspace.pushes) == 1
    replacement = markers(case, "run")[-1]
    assert isinstance(replacement, RunMarker) and replacement.initial_sha != original.initial_sha
    before = writes(case)
    await case.run()
    assert writes(case) == before and len(case.workspace.pushes) == 1


@pytest.mark.unit
async def test_lost_published_clone_recovers_without_second_push(graph_case: GraphCase) -> None:
    case = graph_case
    case.workspace.crash_after = "push"
    with pytest.raises(InjectedCrash):
        await case.run()
    assert case.workspace.prepares
    shutil.rmtree(case.workspace.prepares[-1].repo_dir)
    assert await case.run() == "waiting" and len(case.github.prs) == 1
    assert len(case.workspace.empty_commits) == len(case.workspace.pushes) == 1


@pytest.mark.unit
@pytest.mark.parametrize("update", [{"state": "closed"}, {"is_pull_request": True}])
async def test_rejected_issue_never_prepares_workspace(
    graph_case: GraphCase, update: dict[str, object]
) -> None:
    case = graph_case
    key = issue_key(case)
    case.github.issues[key] = case.github.issues[key].model_copy(update=update)
    assert await case.run() == "blocked"
    assert not case.workspace.prepares and not case.workspace.pushes and not case.github.prs


@pytest.mark.unit
async def test_foreign_remote_head_never_pushes_or_creates_pr(graph_case: GraphCase) -> None:
    case = graph_case
    case.workspace.crash_after = "commit_empty"
    with pytest.raises(InjectedCrash):
        await case.run()
    foreign = await move_remote(case)
    assert await case.run() == "waiting" and question_code(case) == "head_moved"
    assert not case.workspace.pushes and not case.github.prs
    assert await checked(case.origin.bare, "rev-parse", "lgcw/issue-1") == foreign


@pytest.mark.unit
async def test_open_pr_without_journal_never_prepares_or_publishes(graph_case: GraphCase) -> None:
    case = graph_case
    repo = case.ctx.issue_ref.repo
    branch = "lgcw/issue-1"
    case.github.branch_heads[(repo, branch)] = "a" * 40
    await case.github.create_issue_comment(
        *issue_key(case),
        render_marker(
            IntakeMarker(
                snapshot=case.github.issues[issue_key(case)],
                criteria=("Release 0.1.1",),
                command_id=None,
            )
        ),
    )
    await case.github.create_draft_pr(repo, branch, "main", "Owner PR", "Owner data")
    assert await case.run() == "waiting" and question_code(case) == "bootstrap_evidence_missing"
    assert not case.workspace.prepares and not case.workspace.pushes
    assert len(case.github.prs) == 1


class MovedResponseGitHub(FakeGitHub):
    """Simulate an initial PR response whose head differs from the published checkpoint."""

    async def create_draft_pr(
        self, repo: str, head: str, base: str, title: str, body: str
    ) -> PrSnapshot:
        pr = await super().create_draft_pr(repo, head, base, title, body)
        return pr.model_copy(update={"head_sha": "b" * 40})


@pytest.mark.unit
async def test_changed_pr_response_never_records_initial_push(graph_case: GraphCase) -> None:
    case = graph_case
    github = MovedResponseGitHub(clock=case.ctx.clock, login=case.ctx.workflow_login)
    github.issues.update(case.github.issues)
    case.workspace.github = github
    case = case.model_copy(
        update={"github": github, "ctx": case.ctx.model_copy(update={"github": github})}
    )
    assert await case.run() == "waiting" and question_code(case) == "head_moved"
    assert not markers(case, "push")
    assert not any(
        isinstance(marker, BootstrapMarker) and marker.phase == "complete"
        for marker in markers(case, "bootstrap")
    )


@pytest.mark.unit
@pytest.mark.parametrize("same_message", [False, True])
async def test_local_checkpoint_must_have_right_message_and_empty_diff(
    graph_case: GraphCase, same_message: bool
) -> None:
    case = graph_case
    case.workspace.crash_after = "commit_empty"
    with pytest.raises(InjectedCrash):
        await case.run()
    head = await case.workspace.head_sha()
    message = await case.workspace.commit_message(head) if same_message else "foreign local commit"
    checkout = case.workspace.prepares[-1].repo_dir
    if same_message:
        (checkout / "app.py").write_text("unreviewed local change\n")
        await case.workspace.commit_all(message, {})
    else:
        await case.workspace.commit_empty(message)
    assert await case.run() == "waiting" and question_code(case) == "unexpected_local_head"
    assert not case.workspace.pushes and not case.github.prs


@pytest.mark.unit
async def test_recorded_local_head_rewrite_is_not_recheckpointed(graph_case: GraphCase) -> None:
    case = graph_case
    case.github.fail_after("create_issue_comment", 3, InjectedCrash("run intent"))
    with pytest.raises(InjectedCrash):
        await case.run()
    head = await case.workspace.head_sha()
    await case.workspace.commit_empty(await case.workspace.commit_message(head))
    assert await case.run() == "waiting" and question_code(case) == "local_head_changed"
    assert not case.workspace.pushes and not case.github.prs


@pytest.mark.unit
async def test_issue_credential_never_reaches_published_or_local_evidence(
    graph_case: GraphCase,
) -> None:
    case = graph_case
    token = "ghp_" + "A" * 36
    key = issue_key(case)
    case.github.issues[key] = case.github.issues[key].model_copy(
        update={"body": f"## Done when\n- Release 0.1.1\n\nprivate: {token}"}
    )
    await case.run()
    assert case.github.prs
    assert all(
        token not in comment.body
        for comments in case.github.comments.values()
        for comment in comments
    )
    assert all(token not in body for body in case.github.pr_bodies.values())
    assert all(
        token not in path.read_text() for path in case.ctx.log.run_dir.rglob("*") if path.is_file()
    )


@pytest.mark.unit
async def test_setup_tail_stays_in_local_log_only(graph_case: GraphCase) -> None:
    case = graph_case
    text = "synthetic-private-setup-output"
    policy = case.ctx.repo.model_copy(update={"setup": (f"echo {text}",)})
    config = case.ctx.config.model_copy(update={"repos": {policy.full_name: policy}})
    case = case.model_copy(
        update={"ctx": case.ctx.model_copy(update={"repo": policy, "config": config})}
    )
    await case.run()
    assert any(text in path.read_text() for path in case.ctx.log.run_dir.glob("setup-*.log"))
    assert all(
        text not in comment.body
        for comments in case.github.comments.values()
        for comment in comments
    )
    assert all(
        isinstance(item, SetupMarker) and item.tail is None for item in markers(case, "setup")
    )


@pytest.mark.unit
@pytest.mark.parametrize("advance_main", [False, True])
async def test_recreated_unpublished_clone_reinstalls_setup_and_uses_current_base(
    graph_case: GraphCase, advance_main: bool
) -> None:
    case = graph_case
    policy = case.ctx.repo.model_copy(update={"setup": ("echo installed",)})
    config = case.ctx.config.model_copy(update={"repos": {policy.full_name: policy}})
    case = case.model_copy(
        update={"ctx": case.ctx.model_copy(update={"repo": policy, "config": config})}
    )
    case.github.fail_after("create_issue_comment", 5, InjectedCrash("run intent"))
    with pytest.raises(InjectedCrash):
        await case.run()
    assert len(case.workspace.command_runs) == 1 and not case.workspace.pushes
    shutil.rmtree(case.workspace.prepares[-1].repo_dir)
    main = case.origin.base
    if advance_main:
        (case.origin.seed / "new-base.txt").write_text("owner advanced main\n")
        await checked(case.origin.seed, "add", "-A")
        await checked(case.origin.seed, "commit", "-m", "owner main change")
        await checked(case.origin.seed, "push", "origin", "main")
        main = await checked(case.origin.seed, "rev-parse", "HEAD")
    assert await case.run() == "waiting" and len(case.github.prs) == 1
    assert len(case.workspace.command_runs) == 2 and len(case.workspace.pushes) == 1
    replacement = markers(case, "run")[-1]
    assert isinstance(replacement, RunMarker) and replacement.base_sha == main
    assert await checked(case.origin.bare, "rev-parse", "main") == main
