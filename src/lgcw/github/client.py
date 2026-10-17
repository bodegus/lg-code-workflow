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
from lgcw.github.port import (
    CiEvidenceLimitError,
    GitHubPort,
    RequiredPolicyError,
    ResolveReason,
    TokenProvider,
)
from lgcw.live import require_live
from lgcw.models.github import (
    IssueComment,
    JobStep,
    JobView,
    PrDocument,
    PrReview,
    PrSnapshot,
    ReviewCommentDraft,
    ReviewThread,
    RunPullRequest,
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


def _required_context(raw: dict[str, Any], app_key: str) -> str:
    # Verified with GET /apps/github-actions on github.com, 2026-10-13. This adapter
    # currently targets github.com; external check apps cannot be qualified by Actions jobs.
    if raw.get(app_key) not in {None, -1, 15368}:
        raise RequiredPolicyError(
            "unsupported required-check app; owner must qualify that external check"
        )
    return str(raw["context"])


def required_contexts_from_rule(raw: dict[str, Any]) -> tuple[str, ...]:
    """Extract required contexts from a validated SDK rule; missing policy fails closed."""
    if raw.get("type") in {"workflows", "required_deployments", "code_scanning", "merge_queue"}:
        raise RequiredPolicyError(
            f"Required {raw['type']} rule is unsupported by the Actions policy adapter."
        )
    if raw.get("type") != "required_status_checks":
        return ()
    checks = raw["parameters"]["required_status_checks"]
    return tuple(_required_context(check, "integration_id") for check in checks)


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
        steps=tuple(
            JobStep(
                number=step["number"],
                name=step["name"],
                status=step["status"],
                conclusion=step.get("conclusion"),
            )
            for step in data.get("steps", [])
            if "number" in step
        ),
        steps_observed="steps" in data and all("number" in step for step in data["steps"]),
        annotations=tuple(
            "\n".join(
                str(item.get(key) or "") for key in ("title", "message", "raw_details")
            ).strip()
            for item in annotations
        ),
        annotation_paths=tuple(item.get("path") for item in annotations),
        service_output=data.get("service_output", ""),
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
        head_branch=data.get("head_branch"),
        head_repository=(data.get("head_repository") or {}).get("full_name"),
        pull_requests=tuple(pr["number"] for pr in data.get("pull_requests", ())),
        pr_associations=tuple(
            RunPullRequest(number=pr["number"], base_ref=pr["base"]["ref"])
            for pr in data.get("pull_requests", ())
            if (pr.get("base") or {}).get("ref")
        ),
        workflow_path=data.get("path", ""),
        startup_error=data.get("startup_error", ""),
    )


async def execution_from_rest(
    sdk: GitHub[TokenAuthStrategy],
    owner: str,
    name: str,
    data: dict[str, Any],
) -> RunView:
    """Retain a startup failure's check-suite output instead of sending empty feedback."""
    run = _run_from_rest(data)
    if run.conclusion != "startup_failure":
        return run
    suite_id = data.get("check_suite_id")
    if suite_id is None:
        return run.model_copy(
            update={
                "startup_error": (
                    "GitHub reported startup_failure without check-suite error details."
                )
            }
        )
    response = await sdk.rest.checks.async_list_for_suite(
        owner,
        name,
        suite_id,
        filter_="latest",
        per_page=100,
    )
    raw = response.json()
    if raw["total_count"] > 100:
        raise CiEvidenceLimitError("CI startup check count exceeds the 100 observation limit.")
    messages = "\n".join(
        str(check.get("output", {}).get(key) or "")
        for check in raw["check_runs"]
        for key in ("title", "summary", "text")
    ).strip()
    return run.model_copy(
        update={
            "startup_error": messages[:8192]
            or "GitHub reported startup_failure without check-suite output."
        }
    )


_LOG_BYTES = 8 * 1024 * 1024
_MAX_RUNS = 100
_MAX_JOBS = 200


async def bounded_rows[T](rows: AsyncIterator[T], limit: int, label: str) -> list[T]:
    """Stop paginated reads at a hard cap rather than silently dropping required evidence."""
    result: list[T] = []
    async for row in rows:
        if len(result) >= limit:
            raise CiEvidenceLimitError(f"CI {label} count exceeds the {limit} observation limit.")
        result.append(row)
    return result


async def latest_base_run(
    sdk: GitHub[TokenAuthStrategy], owner: str, name: str, workflow_path: str, branch: str
) -> int | None:
    """Ask Actions for one completed base push run of this workflow only."""
    if not workflow_path:
        raise RequiredPolicyError("CI workflow path is missing; cannot qualify its base run.")
    response = await sdk.rest.actions.async_list_workflow_runs(
        owner,
        name,
        workflow_path.rsplit("/", 1)[-1],
        branch=branch,
        event="push",
        status="completed",
        per_page=1,
    )
    items = response.json()["workflow_runs"]
    return items[0]["id"] if items else None


async def download_job_log(
    sdk: GitHub[TokenAuthStrategy], owner: str, name: str, job_id: int
) -> str:
    """Stream at most 8 MiB using the pinned SDK and close the response on every path."""
    async with sdk:
        try:
            response = await sdk.rest.actions.async_download_job_logs_for_workflow_run(
                owner, name, job_id, stream=True
            )
        except RequestFailed as error:
            if error.response.status_code not in {404, 409, 410}:
                raise
            return "Job log unavailable from GitHub; use job steps and annotations."
        data = bytearray()
        try:
            async for chunk in response.aiter_bytes(chunk_size=16384):
                if len(data) + len(chunk) > _LOG_BYTES:
                    raise CiEvidenceLimitError("CI job log exceeds the 8 MiB download limit.")
                data.extend(chunk)
        finally:
            await response.raw_response.aclose()
        return data.decode("utf-8", errors="replace")


async def required_policy(
    sdk: GitHub[TokenAuthStrategy],
    owner: str,
    name: str,
    branch: str,
) -> tuple[str, ...]:
    """Read both protection forms; an ambiguous protected-branch 404 fails closed."""
    contexts: set[str] = set()
    async for rule in sdk.rest.paginate(
        sdk.rest.repos.async_get_branch_rules,
        lambda response: response.parsed_data,
        owner=owner,
        repo=name,
        branch=branch,
        per_page=100,
    ):
        contexts.update(required_contexts_from_rule(_rest_data(rule)))
    try:
        response = await sdk.rest.repos.async_get_status_checks_protection(owner, name, branch)
    except RequestFailed as error:
        if error.response.status_code != 404:
            raise
        branch_response = await sdk.rest.repos.async_get_branch(owner, name, branch)
        protection = branch_response.json().get("protection")
        disabled = False
        if isinstance(protection, dict):
            checks = protection.get("required_status_checks")
            enforcement = checks.get("enforcement_level") if checks is not None else None
            nonempty = bool(checks and (checks.get("checks") or checks.get("contexts")))
            disabled = (
                enforcement in {None, "off"}
                and not (protection.get("enabled") is True and nonempty)
                and (protection.get("enabled") is False or (enforcement == "off" and not nonempty))
            )
        if not disabled:
            raise RequiredPolicyError(
                "Branch is protected or its protection is unknown, "
                "but required checks returned 404. "
                "Owner must supply read access or confirm the complete required policy."
            ) from error
    else:
        raw = _rest_data(response.parsed_data)
        contexts.update(raw.get("contexts", ()))
        contexts.update(_required_context(check, "app_id") for check in raw.get("checks", ()))
    return tuple(sorted(contexts))


async def read_workflow_runs(
    sdk: GitHub[TokenAuthStrategy], repo: str, head_sha: str, pr: PrSnapshot | None
) -> list[RunView]:
    """Filter ownership before hydration and the owned execution cap."""
    owner, name = repo.split("/", 1)
    runs: list[RunView] = []
    items: AsyncIterator[dict[str, Any]] = sdk.rest.paginate(
        sdk.rest.actions.async_list_workflow_runs_for_repo,
        lambda response: response.json()["workflow_runs"],
        owner=owner,
        repo=name,
        head_sha=head_sha,
        per_page=100,
    )
    async for raw in items:
        view = _run_from_rest(raw)
        if pr is not None and (
            view.head_sha != head_sha
            or view.head_repository != repo
            or view.head_branch != pr.head_ref
            or view.event not in {"pull_request", "push"}
            or (view.event == "pull_request" and pr.number not in view.pull_requests)
        ):
            continue
        if len(runs) >= _MAX_RUNS:
            raise CiEvidenceLimitError("CI owned run count exceeds the 100 observation limit.")
        runs.append(await execution_from_rest(sdk, owner, name, raw))
    return runs


async def read_run_jobs(sdk: GitHub[TokenAuthStrategy], repo: str, run_id: int) -> list[JobView]:
    """Read complete bounded job metadata and failure annotations through the SDK."""
    owner, name = repo.split("/", 1)
    response = await sdk.rest.actions.async_get_workflow_run(owner, name, run_id)
    run: dict[str, Any] = dict(response.json())
    jobs: list[JobView] = []
    items: AsyncIterator[dict[str, Any]] = sdk.rest.paginate(
        sdk.rest.actions.async_list_jobs_for_workflow_run,
        lambda response: response.json()["jobs"],
        owner=owner,
        repo=name,
        run_id=run_id,
        filter_="latest",
        per_page=100,
    )
    async for raw in items:
        if len(jobs) >= _MAX_JOBS:
            raise CiEvidenceLimitError("CI job count exceeds the 200 observation limit.")
        raw["workflow_name"] = _run_from_rest(run).workflow
        raw["run_attempt"] = raw.get("run_attempt") or run["run_attempt"]
        annotations: list[dict[str, Any]] = []
        if raw.get("conclusion") in {"failure", "cancelled", "timed_out"} and raw.get(
            "check_run_url"
        ):
            check_id = int(urlsplit(raw["check_run_url"]).path.rstrip("/").rsplit("/", 1)[-1])
            check_response = await sdk.rest.checks.async_get(owner, name, check_id)
            check_output = check_response.json().get("output", {})
            raw["service_output"] = "\n".join(
                str(check_output.get(key) or "") for key in ("title", "summary", "text")
            )
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

    async def find_pr(self, repo: str, head_branch: str) -> PrSnapshot | None:
        """Find any-state branch identity so a closed run cannot be recreated."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        items: AsyncIterator[SdkPullRequestSimple] = sdk.rest.paginate(
            sdk.rest.pulls.async_list,
            owner=owner,
            repo=name,
            state="all",
            head=f"{owner}:{head_branch}",
            sort="created",
            direction="desc",
            per_page=100,
        )
        async for pr in items:
            if pr.head.ref == head_branch:
                return await self.get_pr(repo, pr.number)
        return None

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

    async def open_prs_for_head(self, repo: str, head_branch: str) -> tuple[PrSnapshot, ...]:
        """Read matching open identities; two suffice to prove ambiguity."""
        owner, name = repo.split("/", 1)
        sdk = self._sdk()
        found: list[PrSnapshot] = []
        items: AsyncIterator[SdkPullRequestSimple] = sdk.rest.paginate(
            sdk.rest.pulls.async_list,
            owner=owner,
            repo=name,
            state="open",
            head=f"{owner}:{head_branch}",
            per_page=100,
        )
        async for item in items:
            if item.head.ref == head_branch:
                found.append(await self.get_pr(repo, item.number))
                if len(found) >= 2:
                    break
        return tuple(found)

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

    async def branch_head(self, repo: str, branch: str) -> str | None:
        """Read a branch SHA; only a missing ref is translated to None."""
        owner, name = repo.split("/", 1)
        try:
            response = await self._sdk().rest.git.async_get_ref(owner, name, f"heads/{branch}")
        except RequestFailed as error:
            if error.response.status_code == 404:
                return None
            raise
        return response.parsed_data.object_.sha

    async def get_pr_document(self, repo: str, number: int) -> PrDocument:
        """Read the body and author as one SDK response for bootstrap recovery."""
        owner, name = repo.split("/", 1)
        response = await self._sdk().rest.pulls.async_get(owner, name, number)
        raw = _rest_data(response.parsed_data)
        return PrDocument(
            number=raw["number"],
            author=_author(raw.get("user")),
            body=raw.get("body") or "",
            created_at=raw["created_at"],
            head_ref=raw["head"]["ref"],
            head_sha=raw["head"]["sha"],
        )

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

    async def mark_draft(self, pr_node_id: str) -> None:
        """Invalidate review readiness without changing the PR head or merging."""
        async with self._mutation():
            await self._sdk().async_graphql(
                "mutation($id:ID!){convertPullRequestToDraft(input:{pullRequestId:$id})"
                "{pullRequest{id isDraft}}}",
                {"id": pr_node_id},
            )

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

    async def runs_for_sha(
        self, repo: str, head_sha: str, pr: PrSnapshot | None = None
    ) -> list[RunView]:
        """Read owned exact-head runs using the SDK Link-header paginator."""
        return await read_workflow_runs(self._sdk(), repo, head_sha, pr)

    async def get_run(self, repo: str, run_id: int) -> RunView:
        """Read fresh execution identity through the pinned public SDK."""
        owner, name = repo.split("/", 1)
        response = await self._sdk().rest.actions.async_get_workflow_run(owner, name, run_id)
        return await execution_from_rest(self._sdk(), owner, name, _rest_data(response.parsed_data))

    async def jobs_for_run(self, repo: str, run_id: int) -> list[JobView]:
        """Read latest-attempt jobs including failure and cancellation evidence."""
        return await read_run_jobs(self._sdk(), repo, run_id)

    async def job_log(self, repo: str, job_id: int) -> str:
        """Read a bounded complete log, preserving annotations if GitHub has no log."""
        owner, name = repo.split("/", 1)
        return await download_job_log(self._sdk(), owner, name, job_id)

    async def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        """Dispatch one request; the graph owns its durable action record and recovery."""
        owner, name = repo.split("/", 1)
        async with self._mutation():
            await self._sdk().rest.actions.async_re_run_workflow_failed_jobs(owner, name, run_id)

    async def latest_base_jobs(
        self, repo: str, workflow: str, branch: str, workflow_path: str = ""
    ) -> list[JobView]:
        """Read jobs from the latest completed push run for this exact base/workflow."""
        owner, name = repo.split("/", 1)
        run_id = await latest_base_run(self._sdk(), owner, name, workflow_path, branch)
        return await self.jobs_for_run(repo, run_id) if run_id is not None else []

    async def required_check_contexts(self, repo: str, branch: str) -> tuple[str, ...]:
        """Union both policies and fail closed on ambiguous permissions or workflow rules."""
        owner, name = repo.split("/", 1)
        return await required_policy(self._sdk(), owner, name, branch)
