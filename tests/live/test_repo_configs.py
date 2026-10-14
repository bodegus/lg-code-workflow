"""Read-only qualification of the family-calendar configured job identities."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgcw.config import load_config
from lgcw.github.client import GitHubClient
from lgcw.github.token import GhCliTokenProvider


@pytest.mark.live
async def test_family_calendar_required_job_identities() -> None:
    """Compare trusted policy with the most recent CI run observed before T17 implementation."""
    config = load_config(Path(__file__).parents[2])
    repo = config.repo("bodegus/family-calendar")
    client = GitHubClient(GhCliTokenProvider())
    run = await client.get_run(repo.full_name, 38441965084)
    jobs = await client.jobs_for_run(repo.full_name, run.run_id)
    actual = {(job.workflow, job.name) for job in jobs}
    required = {(check.workflow, check.job) for check in repo.required_checks}
    assert required <= actual
    assert run.workflow_path == ".github/workflows/ci.yml" and run.workflow == "CI"
    print("Observed CI run:", run.run_id, run.head_sha, run.conclusion)
    print("Configured required jobs:", sorted(required))
    print("Actual jobs:", [(job.name, job.conclusion) for job in jobs])
