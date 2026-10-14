"""Service-neutral GitHub records."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from lgcw.models.base import Strict


class PrSnapshot(Strict):
    """Current pull-request identity, head and merge conditions."""

    number: int
    node_id: str
    url: str
    state: Literal["OPEN", "CLOSED", "MERGED"]
    head_ref: str
    head_sha: str
    base_ref: str
    is_draft: bool
    mergeable: Literal["MERGEABLE", "CONFLICTING", "UNKNOWN"]
    merge_state: str
    labels: tuple[str, ...]


class IssueComment(Strict):
    """An issue or PR conversation comment."""

    id: int
    author: str
    body: str
    created_at: datetime


class PrDocument(Strict):
    """Authenticated PR body and branch identity for atomic creation recovery."""

    number: int
    author: str
    body: str
    created_at: datetime
    head_ref: str
    head_sha: str


class ThreadComment(Strict):
    """A comment in a review thread."""

    id: int
    author: str
    body: str


class ReviewThread(Strict):
    """A review thread and its resolution state."""

    node_id: str
    is_resolved: bool
    path: str
    line: int | None
    comments: tuple[ThreadComment, ...]


class PrReview(Strict):
    """A submitted review body, independent of any inline finding threads."""

    id: int
    author: str
    body: str
    head_sha: str | None
    submitted_at: datetime


class ReviewCommentDraft(Strict):
    """One inline comment to publish with a review."""

    path: str
    line: int
    start_line: int | None
    body: str


class RunView(Strict):
    """An Actions workflow run on an exact commit."""

    run_id: int
    workflow: str
    event: str
    status: str
    conclusion: str | None
    head_sha: str
    run_attempt: int
    created_at: datetime | None = None
    head_branch: str | None = None
    head_repository: str | None = None
    pull_requests: tuple[int, ...] = ()
    workflow_path: str = ""
    startup_error: str = ""


class JobView(Strict):
    """An Actions job with failure evidence."""

    job_id: int
    run_id: int
    workflow: str
    name: str
    status: str
    conclusion: str | None
    run_attempt: int
    failed_steps: tuple[str, ...]
    annotations: tuple[str, ...]
    annotation_paths: tuple[str | None, ...] = ()
    service_output: str = ""
    runner_name: str | None
    url: str
