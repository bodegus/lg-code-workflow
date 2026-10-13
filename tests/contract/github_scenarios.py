"""GitHub behavior exercised identically by fake and live adapters."""

from __future__ import annotations

from lgcw.github.port import GitHubPort
from lgcw.models.base import Strict
from lgcw.models.github import PrSnapshot, ReviewCommentDraft
from lgcw.models.issue import IssueRef


class GitHubContractTarget(Strict):
    """Prepared issue, changed branch and reviewable line for a contract run."""

    issue: IssueRef
    branch: str
    base: str
    head_sha: str
    path: str
    line: int


async def scenario_issue_comments_round_trip(
    github: GitHubPort, target: GitHubContractTarget
) -> None:
    """Create a comment and read its authoritative identity and body back."""
    issue = await github.get_issue(target.issue)
    assert (issue.repo, issue.number) == (target.issue.repo, target.issue.number)
    login = await github.viewer_login()
    comment = await github.create_issue_comment(
        issue.repo, issue.number, "lgcw contract: comment\n-builder"
    )
    observed = await github.list_issue_comments(issue.repo, issue.number)
    assert comment in observed
    assert comment.author == login
    assert comment.body == "lgcw contract: comment\n-builder"


async def scenario_draft_pr_then_ready(
    github: GitHubPort, target: GitHubContractTarget
) -> PrSnapshot:
    """Open a draft on a prepared branch, find it, and transition it to ready."""
    repo = target.issue.repo
    pr = await github.create_draft_pr(
        repo,
        target.branch,
        target.base,
        "lgcw contract fixture",
        "Contract only; no merge.\n-builder",
    )
    assert pr.is_draft and pr.head_sha == target.head_sha
    found = await github.find_open_pr(repo, target.branch)
    assert found is not None and found.number == pr.number
    await github.mark_ready(pr.node_id)
    ready = await github.get_pr(repo, pr.number)
    assert not ready.is_draft and ready.state == "OPEN"
    assert ready.head_sha == target.head_sha
    return ready


async def scenario_review_thread_reply_and_resolve(
    github: GitHubPort, target: GitHubContractTarget, pr: PrSnapshot
) -> None:
    """Post an inline review, reply to its thread, and resolve it."""
    repo = target.issue.repo
    review_id = await github.create_review(
        repo,
        pr.number,
        target.head_sha,
        "Contract review\n-builder",
        [
            ReviewCommentDraft(
                path=target.path,
                line=target.line,
                start_line=None,
                body="lgcw contract: finding\n-builder",
            ),
        ],
    )
    assert review_id > 0
    reviews = await github.list_pr_reviews(repo, pr.number)
    receipt = next(review for review in reviews if review.id == review_id)
    assert (receipt.body, receipt.head_sha) == ("Contract review\n-builder", target.head_sha)
    threads = await github.list_review_threads(repo, pr.number)
    thread = next(
        thread
        for thread in threads
        if thread.comments[0].body == "lgcw contract: finding\n-builder"
    )
    assert not thread.is_resolved
    assert (thread.path, thread.line) == (target.path, target.line)
    await github.reply_to_review_comment(
        repo, pr.number, thread.comments[0].id, "lgcw contract: addressed\n-builder"
    )
    await github.resolve_thread(thread.node_id, "ADDRESSED")
    observed = await github.list_review_threads(repo, pr.number)
    resolved = next(item for item in observed if item.node_id == thread.node_id)
    assert resolved.is_resolved
    assert resolved.comments[-1].body == "lgcw contract: addressed\n-builder"
