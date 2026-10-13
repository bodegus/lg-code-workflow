"""Guarded githubkit adapter; credentials and mutations stay in plain code."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from githubkit import GitHub
from githubkit.auth import TokenAuthStrategy
from githubkit.exception import RequestFailed
from pydantic import BaseModel

from lgcw.clock import Clock, SystemClock
from lgcw.github.port import GitHubPort, ResolveReason, TokenProvider
from lgcw.live import require_live
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

if TYPE_CHECKING:
    from githubkit_schemas.v2026_03_10.models import (
        IssueComment as SdkIssueComment,
    )
    from githubkit_schemas.v2026_03_10.models import (
        PullRequestReview as SdkPullRequestReview,
    )
    from githubkit_schemas.v2026_03_10.models import (
        PullRequestSimple as SdkPullRequestSimple,
    )

_PR_QUERY = """
query($owner:String!,$repo:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$repo) { pullRequest(number:$number) {
    id number url state headRefName headRefOid baseRefName isDraft mergeable mergeStateStatus
    labels(first:100,after:$cursor) { nodes { name } pageInfo { hasNextPage endCursor } }
  } }
}
"""
_THREADS_QUERY = """
query($owner:String!,$repo:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$repo) { pullRequest(number:$number) {
    reviewThreads(first:100,after:$cursor) {
      nodes { id isResolved path line comments(first:100) {
        nodes { fullDatabaseId body author { login } }
        pageInfo { hasNextPage endCursor }
      } }
      pageInfo { hasNextPage endCursor }
    }
  } }
}
"""
_COMMENTS_QUERY = """
query($id:ID!,$cursor:String) {
  node(id:$id) { ... on PullRequestReviewThread {
    comments(first:100,after:$cursor) {
      nodes { fullDatabaseId body author { login } }
      pageInfo { hasNextPage endCursor }
    }
  } }
}
"""


def _rest_data(model: BaseModel) -> dict[str, Any]:
    # githubkit's UNSET defaults serialize as strings unless explicitly excluded.
    return model.model_dump(mode="json", exclude_unset=True)


def _review_from_rest(raw: dict[str, Any]) -> PrReview | None:
    if raw.get("state") == "PENDING" or raw.get("submitted_at") is None:
        return None
    return PrReview(
        id=raw["id"],
        author=_author(raw.get("user")),
        body=raw.get("body") or "",
        head_sha=raw.get("commit_id"),
        submitted_at=raw["submitted_at"],
    )


def _author(value: dict[str, Any] | None) -> str:
    return value["login"] if value is not None else "[deleted]"


def issue_from_rest(repo: str, data: dict[str, Any]) -> IssueSnapshot:
    """Map an issue response while preserving evidence that it is actually a PR."""
    return IssueSnapshot(
        repo=repo,
        number=data["number"],
        title=data["title"],
        body=data.get("body") or "",
        author=_author(data.get("user")),
        state=data["state"],
        labels=tuple(
            label if isinstance(label, str) else label["name"] for label in data["labels"]
        ),
        updated_at=data["updated_at"],
        url=data["html_url"],
        is_pull_request=data.get("pull_request") is not None,
    )


def pr_from_graphql(data: dict[str, Any]) -> PrSnapshot:
    """Map the head, draft and merge conditions from a complete PR GraphQL node."""
    return PrSnapshot(
        number=data["number"],
        node_id=data["id"],
        url=data["url"],
        state=data["state"],
        head_ref=data["headRefName"],
        head_sha=data["headRefOid"],
        base_ref=data["baseRefName"],
        is_draft=data["isDraft"],
        mergeable=data["mergeable"],
        merge_state=data["mergeStateStatus"],
        labels=tuple(label["name"] for label in data["labels"]["nodes"]),
    )


def job_from_rest(data: dict[str, Any], annotations: list[dict[str, Any]]) -> JobView:
    """Map failure/cancellation evidence without treating a cancelled timeout as success."""
    return JobView(
        job_id=data["id"],
        run_id=data["run_id"],
        workflow=data["workflow_name"],
        name=data["name"],
        status=data["status"],
        conclusion=data.get("conclusion"),
        run_attempt=data["run_attempt"],
        failed_steps=tuple(
            step["name"]
            for step in data.get("steps", [])
            if step.get("conclusion") in {"failure", "cancelled", "timed_out"}
        ),
        annotations=tuple(
            "\n".join(
                str(item.get(key) or "") for key in ("title", "message", "raw_details")
            ).strip()
            for item in annotations
        ),
        runner_name=data.get("runner_name"),
        url=data["html_url"],
    )


def thread_from_graphql(node: dict[str, Any]) -> ReviewThread:
    """Map all comments with full database IDs, including IDs larger than 32 bits."""
    return ReviewThread(
        node_id=node["id"],
        is_resolved=node["isResolved"],
        path=node["path"],
        line=node.get("line"),
        comments=tuple(
            ThreadComment(
                id=int(comment.get("fullDatabaseId") or comment["databaseId"]),
                author=_author(comment.get("author")),
                body=comment["body"],
            )
            for comment in node["comments"]["nodes"]
        ),
    )


def _run_from_rest(data: dict[str, Any]) -> RunView:
    return RunView(
        run_id=data["id"],
        workflow=data.get("name") or data["path"],
        event=data["event"],
        status=data["status"],
        conclusion=data.get("conclusion"),
        head_sha=data["head_sha"],
        run_attempt=data["run_attempt"],
        created_at=data.get("created_at"),
    )


class GitHubClient(GitHubPort):
    """SDK adapter with explicit live authority, no hidden retries and paced mutations."""

    def __init__(
        self, token_provider: TokenProvider, *, allow_live: bool = False, clock: Clock | None = None
    ) -> None:
        require_live("GitHubClient", allow_live)
        self._tokens = token_provider
        self._clock = clock if clock is not None else SystemClock()
        self._github: GitHub[TokenAuthStrategy] | None = None
        self._mutation_lock = asyncio.Lock()
        self._last_mutation: datetime | None = None

    def _sdk(self) -> GitHub[TokenAuthStrategy]:
        token = self._tokens.token()
        if self._github is None:
            self._github = GitHub(token, auto_retry=False, http_cache=False, timeout=30.0)
        else:
            self._github.auth = TokenAuthStrategy(token)
        return self._github

    @asynccontextmanager
    async def _mutation(self) -> AsyncIterator[None]:
        async with self._mutation_lock:
            if self._last_mutation is not None:
                remaining = 1.0 - (self._clock.now() - self._last_mutation).total_seconds()
                if remaining > 0:
                    await self._clock.sleep(remaining)
            try:
                yield
            finally:
                self._last_mutation = self._clock.now()

    async def viewer_login(self) -> str:
        """Read the authenticated login without exposing its credential."""
        response = await self._sdk().rest.users.async_get_authenticated()
        return response.parsed_data.login

    async def get_issue(self, ref: IssueRef) -> IssueSnapshot:
        """Read the complete issue snapshot and PR-discrimination flag."""
        owner, repo = ref.repo.split("/", 1)
        response = await self._sdk().rest.issues.async_get(owner, repo, ref.number)
        return issue_from_rest(ref.repo, _rest_data(response.parsed_data))

    async def list_issue_comments(self, repo: str, number: int) -> list[IssueComment]:
        """Read all conversation comment pages."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        items: AsyncIterator[SdkIssueComment] = sdk.rest.paginate(
            sdk.rest.issues.async_list_comments,
            owner=owner,
            repo=name,
            issue_number=number,
            per_page=100,
        )
        return [
            IssueComment(
                id=item.id,
                author=_author(_rest_data(item).get("user")),
                body=item.body or "",
                created_at=item.created_at,
            )
            async for item in items
        ]

    async def create_issue_comment(self, repo: str, number: int, body: str) -> IssueComment:
        """Post one comment without automatic retry of an ambiguous write."""
        owner, name = repo.split("/", 1)
        async with self._mutation():
            response = await self._sdk().rest.issues.async_create_comment(
                owner, name, number, data={"body": body}
            )
        raw = _rest_data(response.parsed_data)
        return IssueComment(
            id=raw["id"],
            author=_author(raw.get("user")),
            body=raw.get("body") or "",
            created_at=raw["created_at"],
        )

    async def find_open_pr(self, repo: str, head_branch: str) -> PrSnapshot | None:
        """Find an existing open PR before the caller attempts creation."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        items: AsyncIterator[SdkPullRequestSimple] = sdk.rest.paginate(
            sdk.rest.pulls.async_list,
            owner=owner,
            repo=name,
            state="open",
            head=f"{owner}:{head_branch}",
            per_page=100,
        )
        async for pr in items:
            if pr.head.ref == head_branch:
                return await self.get_pr(repo, pr.number)
        return None

    async def get_pr(self, repo: str, number: int) -> PrSnapshot:
        """Re-read current head/merge conditions and every page of PR labels."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        labels: list[dict[str, Any]] = []
        node: dict[str, Any] | None = None
        async for page in sdk.graphql.paginate(
            _PR_QUERY, {"owner": owner, "repo": name, "number": number}
        ):
            node = page["repository"]["pullRequest"]
            if node is None:
                raise LookupError("Pull request not found")
            labels.extend(node["labels"]["nodes"])
        if node is None:
            raise LookupError("Pull request not found")
        node["labels"]["nodes"] = labels
        return pr_from_graphql(node)

    async def create_draft_pr(
        self, repo: str, head: str, base: str, title: str, body: str
    ) -> PrSnapshot:
        """Create a draft; subsequent reconciliation can find it if the response is lost."""
        owner, name = repo.split("/", 1)
        async with self._mutation():
            response = await self._sdk().rest.pulls.async_create(
                owner,
                name,
                data={"title": title, "head": head, "base": base, "body": body, "draft": True},
            )
        return await self.get_pr(repo, response.parsed_data.number)

    async def update_pr_body(self, repo: str, number: int, body: str) -> None:
        """Replace only the rendered PR body."""
        owner, name = repo.split("/", 1)
        async with self._mutation():
            await self._sdk().rest.pulls.async_update(owner, name, number, data={"body": body})

    async def set_labels(
        self, repo: str, number: int, add: Sequence[str], remove: Sequence[str]
    ) -> None:
        """Provision requested labels if absent, preserving all unrelated labels."""
        owner, name = repo.split("/", 1)
        existing = set((await self.get_issue(IssueRef(repo=repo, number=number))).labels)
        sdk = self._sdk()
        missing = sorted(set(add) - existing)
        for label in missing:
            try:
                await sdk.rest.issues.async_get_label(owner, name, label)
            except RequestFailed as error:
                if error.response.status_code != 404:
                    raise
                async with self._mutation():
                    await sdk.rest.issues.async_create_label(
                        owner, name, data={"name": label, "color": "6f42c1"}
                    )
        if missing:
            async with self._mutation():
                await sdk.rest.issues.async_add_labels(
                    owner, name, number, data={"labels": missing}
                )
        for label in sorted(set(remove) & existing):
            async with self._mutation():
                try:
                    await sdk.rest.issues.async_remove_label(owner, name, number, label)
                except RequestFailed as error:
                    if error.response.status_code != 404:
                        raise

    async def mark_ready(self, pr_node_id: str) -> None:
        """Leave draft without approving or merging the PR."""
        async with self._mutation():
            await self._sdk().async_graphql(
                "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
                "{pullRequest{id isDraft}}}",
                {"id": pr_node_id},
            )

    async def create_review(
        self,
        repo: str,
        number: int,
        commit_sha: str,
        body: str,
        comments: Sequence[ReviewCommentDraft],
    ) -> int:
        """Publish a COMMENT review with exact-head inline locations."""
        owner, name = repo.split("/", 1)
        inline: list[Any] = []
        for comment in comments:
            item: dict[str, Any] = {
                "path": comment.path,
                "line": comment.line,
                "side": "RIGHT",
                "body": comment.body,
            }
            if comment.start_line is not None and comment.start_line < comment.line:
                item.update(start_line=comment.start_line, start_side="RIGHT")
            inline.append(item)
        async with self._mutation():
            response = await self._sdk().rest.pulls.async_create_review(
                owner,
                name,
                number,
                data={
                    "commit_id": commit_sha,
                    "body": body,
                    "event": "COMMENT",
                    "comments": inline,
                },
            )
        return response.parsed_data.id

    async def list_pr_reviews(self, repo: str, number: int) -> list[PrReview]:
        """Read all submitted review receipts, including reviews with no inline comments."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        reviews: list[PrReview] = []
        items: AsyncIterator[SdkPullRequestReview] = sdk.rest.paginate(
            sdk.rest.pulls.async_list_reviews,
            owner=owner,
            repo=name,
            pull_number=number,
            per_page=100,
        )
        async for item in items:
            receipt = _review_from_rest(_rest_data(item))
            if receipt is not None:
                reviews.append(receipt)
        return reviews

    async def list_review_threads(self, repo: str, number: int) -> list[ReviewThread]:
        """Read every thread and every nested page of its comments."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        threads: list[ReviewThread] = []
        async for page in sdk.graphql.paginate(
            _THREADS_QUERY, {"owner": owner, "repo": name, "number": number}
        ):
            for node in page["repository"]["pullRequest"]["reviewThreads"]["nodes"]:
                comments = node["comments"]
                if comments["pageInfo"]["hasNextPage"]:
                    async for more in sdk.graphql.paginate(
                        _COMMENTS_QUERY,
                        {"id": node["id"], "cursor": comments["pageInfo"]["endCursor"]},
                    ):
                        comments["nodes"].extend(more["node"]["comments"]["nodes"])
                threads.append(thread_from_graphql(node))
        return threads

    async def reply_to_review_comment(
        self, repo: str, number: int, comment_id: int, body: str
    ) -> None:
        """Reply to a finding's authoritative numeric comment ID."""
        owner, name = repo.split("/", 1)
        async with self._mutation():
            await self._sdk().rest.pulls.async_create_reply_for_review_comment(
                owner, name, number, comment_id, data={"body": body}
            )

    async def resolve_thread(self, node_id: str, reason: ResolveReason) -> None:
        """Resolve with a reason verified against the live GitHub schema."""
        async with self._mutation():
            await self._sdk().async_graphql(
                "mutation($input:ResolveReviewThreadInput!){resolveReviewThread(input:$input)"
                "{thread{id isResolved}}}",
                {"input": {"threadId": node_id, "resolutionReason": reason}},
            )

    async def runs_for_sha(self, repo: str, head_sha: str) -> list[RunView]:
        """Read exact-head runs using the SDK's Link-header paginator."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        return [
            _run_from_rest(_rest_data(item))
            async for item in sdk.rest.paginate(
                sdk.rest.actions.async_list_workflow_runs_for_repo,
                lambda response: response.parsed_data.workflow_runs,
                owner=owner,
                repo=name,
                head_sha=head_sha,
                per_page=100,
            )
        ]

    async def jobs_for_run(self, repo: str, run_id: int) -> list[JobView]:
        """Read latest-attempt jobs and annotations for failed/cancelled checks."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        response = await sdk.rest.actions.async_get_workflow_run(owner, name, run_id)
        run = response.parsed_data
        jobs: list[JobView] = []
        async for item in sdk.rest.paginate(
            sdk.rest.actions.async_list_jobs_for_workflow_run,
            lambda response: response.parsed_data.jobs,
            owner=owner,
            repo=name,
            run_id=run_id,
            filter_="latest",
            per_page=100,
        ):
            raw = _rest_data(item)
            raw["workflow_name"] = _run_from_rest(_rest_data(run)).workflow
            raw["run_attempt"] = raw.get("run_attempt") or run.run_attempt
            annotations: list[dict[str, Any]] = []
            if raw.get("conclusion") in {"failure", "cancelled", "timed_out"} and raw.get(
                "check_run_url"
            ):
                check_id = int(urlsplit(raw["check_run_url"]).path.rstrip("/").rsplit("/", 1)[-1])
                annotations = [
                    _rest_data(annotation)
                    async for annotation in sdk.rest.paginate(
                        sdk.rest.checks.async_list_annotations,
                        lambda response: response.parsed_data,
                        owner=owner,
                        repo=name,
                        check_run_id=check_id,
                        per_page=100,
                    )
                ]
            jobs.append(job_from_rest(raw, annotations))
        return jobs

    async def job_log(self, repo: str, job_id: int) -> str:
        """Read the downloaded log; callers redact before storing it."""
        owner, name = repo.split("/", 1)
        response = await self._sdk().rest.actions.async_download_job_logs_for_workflow_run(
            owner, name, job_id
        )
        return response.text

    async def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        """Dispatch one request; the graph owns its durable action record and recovery."""
        owner, name = repo.split("/", 1)
        async with self._mutation():
            await self._sdk().rest.actions.async_re_run_workflow_failed_jobs(owner, name, run_id)

    async def latest_base_jobs(self, repo: str, workflow: str, branch: str) -> list[JobView]:
        """Read jobs from the latest completed push run for this exact base/workflow."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        async for item in sdk.rest.paginate(
            sdk.rest.actions.async_list_workflow_runs_for_repo,
            lambda response: response.parsed_data.workflow_runs,
            owner=owner,
            repo=name,
            branch=branch,
            event="push",
            status="completed",
            per_page=100,
        ):
            if _run_from_rest(_rest_data(item)).workflow == workflow:
                return await self.jobs_for_run(repo, item.id)
        return []
