"""In-memory GitHub port with fake-time CI and post-effect crash injection."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from lgcw.clock import Clock
from lgcw.github.port import GitHubPort, ResolveReason
from lgcw.models.github import (
    IssueComment,
    JobView,
    PrReview,
    PrSnapshot,
    ReviewCommentDraft,
    ReviewThread,
    RunView,
    ThreadComment,
)
from lgcw.models.issue import IssueRef, IssueSnapshot
from tests.fakes.clock import FakeClock


class FakeGitHub(GitHubPort):
    """Deterministic service state; mutations remain visible after injected failures."""

    def __init__(self, *, clock: Clock | None = None, login: str = "bodegus") -> None:
        self.clock = clock if clock is not None else FakeClock(datetime(2026, 10, 13, tzinfo=UTC))
        self.login = login
        self.issues: dict[tuple[str, int], IssueSnapshot] = {}
        self.comments: dict[tuple[str, int], list[IssueComment]] = {}
        self.prs: dict[tuple[str, int], PrSnapshot] = {}
        self.pr_bodies: dict[tuple[str, int], str] = {}
        self.pr_titles: dict[tuple[str, int], str] = {}
        self.branch_heads: dict[tuple[str, str], str] = {}
        self.threads: dict[tuple[str, int], list[ReviewThread]] = {}
        self.reviews: dict[tuple[str, int], list[PrReview]] = {}
        self.resolutions: dict[str, ResolveReason] = {}
        self.runs: dict[str, list[RunView]] = {}
        self.jobs: dict[int, list[JobView]] = {}
        self.logs: dict[int, str] = {}
        self.base_jobs: dict[tuple[str, str, str], list[JobView]] = {}
        self.rerun_requests: dict[tuple[str, int], int] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._call_counts: dict[str, int] = {}
        self._failures: dict[str, tuple[int, Exception]] = {}
        self._timelines: dict[str, list[tuple[float, list[RunView], list[JobView]]]] = {}
        self._timeline_starts: dict[str, datetime] = {}
        self._next_pr = 100
        self._next_comment = 1
        self._next_review = 1

    def fail_after(self, method: str, n: int, exc: Exception) -> None:
        """Fail once after the nth subsequent completed call, after applying its effect."""
        if n < 1:
            raise ValueError("failure call number must be positive")
        self._failures[method] = (self._call_counts.get(method, 0) + n, exc)

    def script_runs(
        self, head_sha: str, timeline: list[tuple[float, list[RunView], list[JobView]]]
    ) -> None:
        """Script snapshots at offsets from the fake clock's current instant."""
        self._timelines[head_sha] = sorted(timeline, key=lambda item: item[0])
        self._timeline_starts[head_sha] = self.clock.now()

    def _record(self, method: str, **arguments: object) -> None:
        self.calls.append((method, arguments))
        self._call_counts[method] = self._call_counts.get(method, 0) + 1

    def _finish(self, method: str) -> None:
        failure = self._failures.get(method)
        if failure is not None and self._call_counts[method] == failure[0]:
            del self._failures[method]
            raise failure[1]

    def _comment_id(self) -> int:
        existing = [comment.id for comments in self.comments.values() for comment in comments]
        existing.extend(
            comment.id
            for threads in self.threads.values()
            for thread in threads
            for comment in thread.comments
        )
        value = max([self._next_comment, *(identifier + 1 for identifier in existing)])
        self._next_comment = value + 1
        return value

    def _current_pr(self, key: tuple[str, int]) -> PrSnapshot:
        pr = self.prs[key]
        head = self.branch_heads.get((key[0], pr.head_ref), pr.head_sha)
        current = pr.model_copy(update={"head_sha": head})
        self.prs[key] = current
        return current

    def _timeline(self, head_sha: str) -> tuple[list[RunView], list[JobView]]:
        elapsed = (self.clock.now() - self._timeline_starts[head_sha]).total_seconds()
        snapshot: tuple[list[RunView], list[JobView]] = ([], [])
        for offset, runs, jobs in self._timelines[head_sha]:
            if offset <= elapsed:
                snapshot = (runs, jobs)
        return snapshot

    async def viewer_login(self) -> str:
        """Return the synthetic workflow identity."""
        self._record("viewer_login")
        self._finish("viewer_login")
        return self.login

    async def get_issue(self, ref: IssueRef) -> IssueSnapshot:
        """Read a seeded issue."""
        self._record("get_issue", ref=ref)
        issue = self.issues[(ref.repo, ref.number)]
        self._finish("get_issue")
        return issue

    async def list_issue_comments(self, repo: str, number: int) -> list[IssueComment]:
        """Read conversation comments without conflating review bodies."""
        self._record("list_issue_comments", repo=repo, number=number)
        result = list(self.comments.get((repo, number), []))
        self._finish("list_issue_comments")
        return result

    async def create_issue_comment(self, repo: str, number: int, body: str) -> IssueComment:
        """Append a uniquely identified conversation comment."""
        self._record("create_issue_comment", repo=repo, number=number, body=body)
        key = (repo, number)
        if key not in self.issues and key not in self.prs:
            raise KeyError(key)
        comment = IssueComment(
            id=self._comment_id(), author=self.login, body=body, created_at=self.clock.now()
        )
        self.comments.setdefault(key, []).append(comment)
        self._finish("create_issue_comment")
        return comment

    async def find_open_pr(self, repo: str, head_branch: str) -> PrSnapshot | None:
        """Find only open PRs in the requested repository and branch."""
        self._record("find_open_pr", repo=repo, head_branch=head_branch)
        found = next(
            (
                self._current_pr(key)
                for key, pr in self.prs.items()
                if key[0] == repo and pr.head_ref == head_branch and pr.state == "OPEN"
            ),
            None,
        )
        self._finish("find_open_pr")
        return found

    async def get_pr(self, repo: str, number: int) -> PrSnapshot:
        """Read the current branch head and PR state."""
        self._record("get_pr", repo=repo, number=number)
        result = self._current_pr((repo, number))
        self._finish("get_pr")
        return result

    async def create_draft_pr(
        self, repo: str, head: str, base: str, title: str, body: str
    ) -> PrSnapshot:
        """Create a draft on a prepared branch, without merging or pushing."""
        self._record("create_draft_pr", repo=repo, head=head, base=base, title=title, body=body)
        head_sha = self.branch_heads[(repo, head)]
        while (repo, self._next_pr) in self.issues or (repo, self._next_pr) in self.prs:
            self._next_pr += 1
        number = self._next_pr
        self._next_pr += 1
        pr = PrSnapshot(
            number=number,
            node_id=f"pr-{repo}-{number}",
            url=f"https://github.test/{repo}/pull/{number}",
            state="OPEN",
            head_ref=head,
            head_sha=head_sha,
            base_ref=base,
            is_draft=True,
            mergeable="MERGEABLE",
            merge_state="CLEAN",
            labels=(),
        )
        key = (repo, number)
        self.prs[key] = pr
        self.pr_bodies[key] = body
        self.pr_titles[key] = title
        self._finish("create_draft_pr")
        return pr

    async def update_pr_body(self, repo: str, number: int, body: str) -> None:
        """Update an existing PR's human-readable body."""
        self._record("update_pr_body", repo=repo, number=number, body=body)
        self.prs[(repo, number)]
        self.pr_bodies[(repo, number)] = body
        self._finish("update_pr_body")

    async def set_labels(
        self, repo: str, number: int, add: Sequence[str], remove: Sequence[str]
    ) -> None:
        """Change only requested labels on an issue or PR."""
        self._record("set_labels", repo=repo, number=number, add=tuple(add), remove=tuple(remove))
        key = (repo, number)
        if key in self.prs:
            pr = self.prs[key]
            labels = tuple(sorted((set(pr.labels) | set(add)) - set(remove)))
            self.prs[key] = pr.model_copy(update={"labels": labels})
        else:
            issue = self.issues[key]
            labels = tuple(sorted((set(issue.labels) | set(add)) - set(remove)))
            self.issues[key] = issue.model_copy(update={"labels": labels})
        self._finish("set_labels")

    async def mark_ready(self, pr_node_id: str) -> None:
        """Transition one known draft without merging it."""
        self._record("mark_ready", pr_node_id=pr_node_id)
        for key, pr in self.prs.items():
            if pr.node_id == pr_node_id:
                self.prs[key] = pr.model_copy(update={"is_draft": False})
                self._finish("mark_ready")
                return
        raise KeyError(pr_node_id)

    async def create_review(
        self,
        repo: str,
        number: int,
        commit_sha: str,
        body: str,
        comments: Sequence[ReviewCommentDraft],
    ) -> int:
        """Record a COMMENT review and its inline threads as a single effect."""
        self._record(
            "create_review",
            repo=repo,
            number=number,
            commit_sha=commit_sha,
            body=body,
            comments=tuple(comments),
        )
        self.prs[(repo, number)]
        review_id = self._next_review
        self._next_review += 1
        self.reviews.setdefault((repo, number), []).append(
            PrReview(
                id=review_id,
                author=self.login,
                body=body,
                head_sha=commit_sha,
                submitted_at=self.clock.now(),
            )
        )
        for index, comment in enumerate(comments):
            thread = ReviewThread(
                node_id=f"thread-{review_id}-{index}",
                is_resolved=False,
                path=comment.path,
                line=comment.line,
                comments=(
                    ThreadComment(id=self._comment_id(), author=self.login, body=comment.body),
                ),
            )
            self.threads.setdefault((repo, number), []).append(thread)
        self._finish("create_review")
        return review_id

    async def list_review_threads(self, repo: str, number: int) -> list[ReviewThread]:
        """Read inline threads, including replies and resolution state."""
        self._record("list_review_threads", repo=repo, number=number)
        result = list(self.threads.get((repo, number), []))
        self._finish("list_review_threads")
        return result

    async def list_pr_reviews(self, repo: str, number: int) -> list[PrReview]:
        """Read submitted review receipts without relying on inline threads."""
        self._record("list_pr_reviews", repo=repo, number=number)
        result = list(self.reviews.get((repo, number), []))
        self._finish("list_pr_reviews")
        return result

    async def reply_to_review_comment(
        self, repo: str, number: int, comment_id: int, body: str
    ) -> None:
        """Append a reply to the matching finding thread."""
        self._record(
            "reply_to_review_comment", repo=repo, number=number, comment_id=comment_id, body=body
        )
        threads = self.threads.get((repo, number), [])
        for index, thread in enumerate(threads):
            if any(comment.id == comment_id for comment in thread.comments):
                reply = ThreadComment(id=self._comment_id(), author=self.login, body=body)
                threads[index] = thread.model_copy(update={"comments": (*thread.comments, reply)})
                self._finish("reply_to_review_comment")
                return
        raise KeyError(comment_id)

    async def resolve_thread(self, node_id: str, reason: ResolveReason) -> None:
        """Resolve one thread and record the logical disposition."""
        self._record("resolve_thread", node_id=node_id, reason=reason)
        for threads in self.threads.values():
            for index, thread in enumerate(threads):
                if thread.node_id == node_id:
                    threads[index] = thread.model_copy(update={"is_resolved": True})
                    self.resolutions[node_id] = reason
                    self._finish("resolve_thread")
                    return
        raise KeyError(node_id)

    async def runs_for_sha(self, repo: str, head_sha: str) -> list[RunView]:
        """Return the scripted run snapshot at current fake time."""
        self._record("runs_for_sha", repo=repo, head_sha=head_sha)
        if head_sha in self._timelines:
            result = list(self._timeline(head_sha)[0])
        else:
            result = list(self.runs.get(head_sha, []))
        self._finish("runs_for_sha")
        return result

    async def jobs_for_run(self, repo: str, run_id: int) -> list[JobView]:
        """Return the current scripted jobs for a run."""
        self._record("jobs_for_run", repo=repo, run_id=run_id)
        result = list(self.jobs.get(run_id, []))
        for head_sha in self._timelines:
            runs, jobs = self._timeline(head_sha)
            if any(run.run_id == run_id for run in runs):
                result = [job for job in jobs if job.run_id == run_id]
        self._finish("jobs_for_run")
        return result

    async def job_log(self, repo: str, job_id: int) -> str:
        """Read a seeded job log."""
        self._record("job_log", repo=repo, job_id=job_id)
        result = self.logs[job_id]
        self._finish("job_log")
        return result

    async def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        """Record a rerun request; subsequent observations come from the timeline."""
        self._record("rerun_failed_jobs", repo=repo, run_id=run_id)
        key = (repo, run_id)
        self.rerun_requests[key] = self.rerun_requests.get(key, 0) + 1
        self._finish("rerun_failed_jobs")

    async def latest_base_jobs(self, repo: str, workflow: str, branch: str) -> list[JobView]:
        """Read the seeded latest completed base run's jobs."""
        self._record("latest_base_jobs", repo=repo, workflow=workflow, branch=branch)
        result = list(self.base_jobs.get((repo, workflow, branch), []))
        self._finish("latest_base_jobs")
        return result
