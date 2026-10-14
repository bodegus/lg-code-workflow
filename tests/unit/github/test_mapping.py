"""Sanitized service payloads map to strict boundaries without losing gate evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lgcw.github.client import issue_from_rest, job_from_rest, pr_from_graphql, thread_from_graphql

FIXTURES = Path(__file__).parents[2] / "fixtures" / "github"


def _fixture(name: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return value


@pytest.mark.unit
@pytest.mark.parametrize("mergeable", ["MERGEABLE", "CONFLICTING", "UNKNOWN"])
def test_pr_from_graphql_maps_mergeable(mergeable: str) -> None:
    raw = _fixture("pr.json")
    pr = pr_from_graphql(raw | {"mergeable": mergeable})
    assert pr.mergeable == mergeable
    assert pr.head_sha == "a" * 40
    assert pr.labels == ("lgcw:active",)
    assert pr.is_draft


@pytest.mark.unit
def test_job_from_rest_timeout_annotation() -> None:
    job = job_from_rest(_fixture("job.json"), [{"message": "exceeded the maximum execution time"}])
    assert job.conclusion == "cancelled"
    assert job.failed_steps == ("Run tests",)
    assert "exceeded the maximum execution time" in job.annotations[0]
    assert job.run_attempt == 2 and job.runner_name is None


@pytest.mark.unit
def test_thread_from_graphql_uses_full_database_id() -> None:
    thread = thread_from_graphql(_fixture("thread.json"))
    assert thread.comments[0].id == 4294967299
    assert thread.comments[0].author == "example"
    assert not thread.is_resolved


@pytest.mark.unit
def test_issue_snapshot_flags_pull_request() -> None:
    raw = _fixture("issue.json")
    issue = issue_from_rest("example/sandbox", raw)
    assert not issue.is_pull_request
    pr_issue = issue_from_rest("example/sandbox", raw | {"pull_request": {"url": "synthetic"}})
    assert pr_issue.is_pull_request


@pytest.mark.unit
def test_issue_null_pull_request_field_is_not_a_pr() -> None:
    # SDK dumps include optional default fields even when the wire response omitted them.
    raw = _fixture("issue.json") | {"pull_request": None}
    assert not issue_from_rest("example/sandbox", raw).is_pull_request


@pytest.mark.unit
def test_job_annotations_preserve_path_provenance() -> None:
    annotations = [
        {"path": "tests/test_pool.py", "message": "runner offline"},
        {"path": ".github", "message": "runner lost communication"},
    ]
    result = job_from_rest(_fixture("job.json"), annotations)
    assert result.annotation_paths == ("tests/test_pool.py", ".github")
    assert result.annotations == ("runner offline", "runner lost communication")
