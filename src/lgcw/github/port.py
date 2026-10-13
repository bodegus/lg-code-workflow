"""Typed GitHub capabilities; merging is intentionally absent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

from lgcw.models.github import (
    IssueComment,
    JobView,
    PrDocument,
    PrReview,
    PrSnapshot,
    ReviewCommentDraft,
    ReviewThread,
    RunView,
)
from lgcw.models.issue import IssueRef, IssueSnapshot

type ResolveReason = Literal["ADDRESSED", "WONT_FIX", "INVALID"]


@runtime_checkable
class TokenProvider(Protocol):
    """Code-only access to a GitHub credential."""

    def token(self) -> str:
        """Return a token without printing or logging it."""
        ...


@runtime_checkable
class GitHubPort(Protocol):
    """GitHub operations available to deterministic workflow nodes."""

    async def viewer_login(self) -> str:
        """Return the authenticated workflow login."""
        ...

    async def get_issue(self, ref: IssueRef) -> IssueSnapshot:
        """Read an issue snapshot."""
        ...

    async def list_issue_comments(self, repo: str, number: int) -> list[IssueComment]:
        """Read issue or PR conversation comments."""
        ...

    async def create_issue_comment(self, repo: str, number: int, body: str) -> IssueComment:
        """Publish a conversation comment, including its own workflow marker."""
        ...

    async def find_open_pr(self, repo: str, head_branch: str) -> PrSnapshot | None:
        """Find an open PR for a branch."""
        ...

    async def get_pr(self, repo: str, number: int) -> PrSnapshot:
        """Read the current head and merge conditions."""
        ...

    async def branch_head(self, repo: str, branch: str) -> str | None:
        """Read a remote branch without creating it; absence returns None."""
        ...

    async def get_pr_document(self, repo: str, number: int) -> PrDocument:
        """Read the authenticated body marker after a lost create response."""
        ...

    async def create_draft_pr(
        self, repo: str, head: str, base: str, title: str, body: str
    ) -> PrSnapshot:
        """Open a draft PR on an existing non-default branch."""
        ...

    async def update_pr_body(self, repo: str, number: int, body: str) -> None:
        """Replace the rendered PR body."""
        ...

    async def set_labels(
        self, repo: str, number: int, add: Sequence[str], remove: Sequence[str]
    ) -> None:
        """Add and remove only the specified labels."""
        ...

    async def mark_ready(self, pr_node_id: str) -> None:
        """Transition a draft PR to ready for review without merging it."""
        ...

    async def create_review(
        self,
        repo: str,
        number: int,
        commit_sha: str,
        body: str,
        comments: Sequence[ReviewCommentDraft],
    ) -> int:
        """Post a COMMENT review on an exact commit with inline findings."""
        ...

    async def list_review_threads(self, repo: str, number: int) -> list[ReviewThread]:
        """Read review-thread comments and resolution state."""
        ...

    async def list_pr_reviews(self, repo: str, number: int) -> list[PrReview]:
        """Read submitted review bodies, including reviews with no inline comments."""
        ...

    async def reply_to_review_comment(
        self, repo: str, number: int, comment_id: int, body: str
    ) -> None:
        """Reply to the original inline finding comment."""
        ...

    async def resolve_thread(self, node_id: str, reason: ResolveReason) -> None:
        """Resolve a thread after recording the matching disposition."""
        ...

    async def runs_for_sha(self, repo: str, head_sha: str) -> list[RunView]:
        """Read workflow runs for an exact head."""
        ...

    async def jobs_for_run(self, repo: str, run_id: int) -> list[JobView]:
        """Read jobs, including failure or cancellation annotations."""
        ...

    async def job_log(self, repo: str, job_id: int) -> str:
        """Read the full job log for later redaction and trimming."""
        ...

    async def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        """Request a rerun of failed jobs."""
        ...

    async def latest_base_jobs(self, repo: str, workflow: str, branch: str) -> list[JobView]:
        """Read the latest completed base push run's jobs for a workflow."""
        ...
