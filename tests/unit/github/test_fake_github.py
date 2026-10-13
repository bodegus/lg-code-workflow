"""Real contract scenarios over the fake, plus clocks and crash injection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lgcw.github.port import GitHubPort
from lgcw.models.github import JobView, RunView
from lgcw.models.issue import IssueRef, IssueSnapshot
from tests.contract.github_scenarios import (
    GitHubContractTarget,
    scenario_draft_pr_then_ready,
    scenario_issue_comments_round_trip,
    scenario_review_thread_reply_and_resolve,
)
from tests.fakes.clock import FakeClock
from tests.fakes.github import FakeGitHub


@pytest.fixture
def target() -> GitHubContractTarget:
    return GitHubContractTarget(
        issue=IssueRef(repo="example/sandbox", number=12),
        branch="lgcw/contract",
        base="main",
        head_sha="a" * 40,
        path="contract.txt",
        line=1,
    )


@pytest.fixture
def github(target: GitHubContractTarget) -> FakeGitHub:
    fake = FakeGitHub(login="example")
    fake.issues[(target.issue.repo, target.issue.number)] = IssueSnapshot(
        repo=target.issue.repo,
        number=target.issue.number,
        title="Contract fixture",
        body="Synthetic",
        author="example",
        state="open",
        labels=(),
        updated_at=fake.clock.now(),
        url="https://example.test/12",
    )
    fake.branch_heads[(target.issue.repo, target.branch)] = target.head_sha
    return fake


@pytest.mark.unit
async def test_issue_comments_round_trip(github: FakeGitHub, target: GitHubContractTarget) -> None:
    await scenario_issue_comments_round_trip(github, target)


@pytest.mark.unit
async def test_draft_pr_then_ready(github: FakeGitHub, target: GitHubContractTarget) -> None:
    await scenario_draft_pr_then_ready(github, target)


@pytest.mark.unit
async def test_review_thread_reply_and_resolve(
    github: FakeGitHub, target: GitHubContractTarget
) -> None:
    pr = await scenario_draft_pr_then_ready(github, target)
    await scenario_review_thread_reply_and_resolve(github, target, pr)


@pytest.mark.unit
async def test_review_without_inline_comments_can_be_recovered(
    github: FakeGitHub, target: GitHubContractTarget
) -> None:
    pr = await scenario_draft_pr_then_ready(github, target)
    review_id = await github.create_review(
        target.issue.repo, pr.number, target.head_sha, "durable review receipt", []
    )
    reviews = await github.list_pr_reviews(target.issue.repo, pr.number)
    assert len(reviews) == 1
    assert (reviews[0].id, reviews[0].head_sha, reviews[0].body) == (
        review_id,
        target.head_sha,
        "durable review receipt",
    )
    assert await github.list_review_threads(target.issue.repo, pr.number) == []


@pytest.mark.unit
async def test_failure_injected_after_side_effect(
    github: FakeGitHub, target: GitHubContractTarget
) -> None:
    github.fail_after("create_issue_comment", 1, RuntimeError("simulated crash"))
    with pytest.raises(RuntimeError, match="simulated crash"):
        await github.create_issue_comment(target.issue.repo, target.issue.number, "persisted")
    comments = await github.list_issue_comments(target.issue.repo, target.issue.number)
    assert len(comments) == 1 and comments[0].body == "persisted"
    await github.create_issue_comment(target.issue.repo, target.issue.number, "second")
    assert len(await github.list_issue_comments(target.issue.repo, target.issue.number)) == 2


@pytest.mark.unit
async def test_labels_body_and_head_follow_current_records(
    github: FakeGitHub, target: GitHubContractTarget
) -> None:
    repo = target.issue.repo
    assert await github.find_open_pr(repo, "absent") is None
    pr = await github.create_draft_pr(repo, target.branch, target.base, "Title", "Original")
    await github.update_pr_body(repo, pr.number, "Updated")
    assert github.pr_bodies[(repo, pr.number)] == "Updated"
    await github.set_labels(repo, pr.number, ["active", "waiting"], [])
    await github.set_labels(repo, pr.number, ["ready"], ["active"])
    assert set((await github.get_pr(repo, pr.number)).labels) == {"waiting", "ready"}
    await github.set_labels(repo, target.issue.number, ["issue-label"], [])
    assert (await github.get_issue(target.issue)).labels == ("issue-label",)
    github.branch_heads[(repo, target.branch)] = "b" * 40
    assert (await github.get_pr(repo, pr.number)).head_sha == "b" * 40


@pytest.mark.unit
async def test_scripted_ci_tracks_fake_clock() -> None:
    clock = FakeClock(datetime(2026, 10, 13, tzinfo=UTC))
    github = FakeGitHub(clock=clock)
    run = RunView(
        run_id=1,
        workflow="CI",
        event="pull_request",
        status="queued",
        conclusion=None,
        head_sha="a",
        run_attempt=1,
    )
    job = JobView(
        job_id=1,
        run_id=1,
        workflow="CI",
        name="test",
        status="completed",
        conclusion="success",
        run_attempt=1,
        failed_steps=(),
        annotations=(),
        runner_name="synthetic",
        url="https://example.test/job",
    )
    completed = run.model_copy(update={"status": "completed", "conclusion": "success"})
    github.script_runs("a", [(0, [run], []), (10, [completed], [job])])
    assert (await github.runs_for_sha("example/sandbox", "a")) == [run]
    assert await github.jobs_for_run("example/sandbox", 1) == []
    await clock.sleep(10)
    assert (await github.runs_for_sha("example/sandbox", "a")) == [completed]
    assert await github.jobs_for_run("example/sandbox", 1) == [job]
    github.logs[1] = "synthetic log"
    github.base_jobs[("example/sandbox", "CI", "main")] = [job]
    assert await github.job_log("example/sandbox", 1) == "synthetic log"
    assert await github.latest_base_jobs("example/sandbox", "CI", "main") == [job]
    await github.rerun_failed_jobs("example/sandbox", 1)
    assert github.calls[-1][0] == "rerun_failed_jobs"


@pytest.mark.unit
def test_port_and_fake_have_no_merge_operation() -> None:
    assert not hasattr(GitHubPort, "merge")
    assert not hasattr(FakeGitHub, "merge")


@pytest.mark.unit
async def test_reply_to_reply_is_rejected(github: FakeGitHub, target: GitHubContractTarget) -> None:
    pr = await scenario_draft_pr_then_ready(github, target)
    await scenario_review_thread_reply_and_resolve(github, target, pr)
    thread = (await github.list_review_threads(target.issue.repo, pr.number))[0]
    with pytest.raises(ValueError, match="root"):
        await github.reply_to_review_comment(
            target.issue.repo, pr.number, thread.comments[-1].id, "invalid"
        )
    assert len((await github.list_review_threads(target.issue.repo, pr.number))[0].comments) == 2
