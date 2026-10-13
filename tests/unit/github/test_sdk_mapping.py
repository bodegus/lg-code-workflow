"""Mapping regressions exercise validated pinned SDK models, including UNSET defaults."""

from __future__ import annotations

from typing import Any

import pytest
from githubkit_schemas.v2026_03_10.models import (
    Issue,
    MinimalRepository,
    PullRequestReview,
    SimpleUser,
    WorkflowRun,
)

from lgcw.github.client import _rest_data, _review_from_rest, _run_from_rest, issue_from_rest

STAMP = "2026-10-13T00:00:00Z"
URL = "https://example.test/fixture"


def review_payload() -> dict[str, Any]:
    """Return a pending wire response with submitted_at genuinely absent."""
    return dict(
        id=1,
        node_id="R1",
        user=None,
        body="",
        state="PENDING",
        html_url=URL,
        pull_request_url=URL,
        _links={"html": {"href": URL}, "pull_request": {"href": URL}},
        commit_id=None,
        author_association="OWNER",
    )


@pytest.mark.unit
def test_plain_sdk_issue_is_not_a_pull_request() -> None:
    raw: dict[str, Any] = {key: URL for key in Issue.model_fields if key.endswith("url")}
    raw.update(
        id=1,
        node_id="I1",
        number=1,
        state="open",
        title="Issue",
        user=None,
        labels=[],
        milestone=None,
        locked=False,
        comments=0,
        closed_at=None,
        created_at=STAMP,
        updated_at=STAMP,
    )
    sdk = Issue.model_validate(raw)
    assert sdk.model_dump(mode="json")["pull_request"] == "<UNSET>"
    assert not issue_from_rest("example/sandbox", _rest_data(sdk)).is_pull_request


@pytest.mark.unit
def test_sdk_pending_review_is_not_a_submitted_receipt() -> None:
    sdk = PullRequestReview.model_validate(review_payload())
    assert _review_from_rest(_rest_data(sdk)) is None


@pytest.mark.unit
def test_sdk_submitted_review_tolerates_null_commit() -> None:
    raw = review_payload() | {"state": "COMMENTED", "submitted_at": STAMP}
    receipt = _review_from_rest(_rest_data(PullRequestReview.model_validate(raw)))
    assert receipt is not None and receipt.head_sha is None


@pytest.mark.unit
def test_sdk_run_missing_name_falls_back_to_workflow_path() -> None:
    user: dict[str, Any] = {
        key: URL for key, field in SimpleUser.model_fields.items() if field.is_required()
    }
    user.update(id=1, node_id="U1", login="owner", type="User", site_admin=False, gravatar_id=None)
    repo: dict[str, Any] = {
        key: URL for key, field in MinimalRepository.model_fields.items() if field.is_required()
    }
    repo.update(
        id=1,
        node_id="P1",
        name="sandbox",
        full_name="example/sandbox",
        owner=user,
        private=False,
        description=None,
        fork=False,
    )
    raw: dict[str, Any] = {
        key: URL for key, field in WorkflowRun.model_fields.items() if field.is_required()
    }
    raw.update(
        id=1,
        node_id="W1",
        head_branch="main",
        head_sha="a" * 40,
        path=".github/workflows/ci.yml",
        run_number=1,
        run_attempt=1,
        event="push",
        status="completed",
        conclusion="success",
        workflow_id=1,
        pull_requests=[],
        created_at=STAMP,
        updated_at=STAMP,
        head_commit=None,
        repository=repo,
        head_repository=repo,
        display_title="CI",
    )
    sdk = WorkflowRun.model_validate(raw)
    assert _run_from_rest(_rest_data(sdk)).workflow == ".github/workflows/ci.yml"
