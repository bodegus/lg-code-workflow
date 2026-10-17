"""Read-only qualification of the family-calendar configured job identities."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
from githubkit import GitHub, TokenAuthStrategy

from lgcw.config import load_config
from lgcw.github.client import GitHubClient
from lgcw.github.token import GhCliTokenProvider
from lgcw.live import require_live


@pytest.mark.live
async def test_family_calendar_required_job_identities() -> None:
    """Compare R2 Quality/container policy with its exact-head green CI run."""
    config = load_config(Path(__file__).parents[2])
    repo = config.repo("bodegus/family-calendar")
    client = GitHubClient(GhCliTokenProvider())
    run = await client.get_run(repo.full_name, 38553158311)
    jobs = await client.jobs_for_run(repo.full_name, run.run_id)
    actual = {(job.workflow, job.name) for job in jobs}
    required = {(check.workflow, check.job) for check in repo.required_checks}
    assert required <= actual
    assert run.workflow_path == ".github/workflows/ci.yml" and run.workflow == "CI"
    print("Observed CI run:", run.run_id, run.head_sha, run.conclusion)
    print("Configured required jobs:", sorted(required))
    print("Actual jobs:", [(job.name, job.conclusion) for job in jobs])


@pytest.mark.live
async def test_oc2_portable_gate_files_exist_on_main() -> None:
    """A removed or renamed portable test must fail qualification loudly."""
    require_live("OC2 gate inventory", False)
    config = load_config(Path(__file__).parents[2])
    repo = config.repo("bodegus/openclaw2-deploy")
    files = {
        arg
        for command in repo.gate
        for arg in shlex.split(command)
        if arg.startswith("tests/unit/") and arg.endswith(".py")
    }
    assert files, "The portable gate must name whole unit files"
    sdk: GitHub[TokenAuthStrategy] = GitHub(
        GhCliTokenProvider().token(), auto_retry=False, http_cache=False, timeout=30.0
    )
    response = await sdk.rest.git.async_get_tree(
        owner="bodegus", repo="openclaw2-deploy", tree_sha=repo.default_branch, recursive="true"
    )
    tree = response.parsed_data
    assert not tree.truncated, "A truncated inventory cannot prove file existence"
    actual = {entry.path for entry in tree.tree if entry.type == "blob"}
    assert files <= actual, f"Missing portable unit files: {sorted(files - actual)}"
    print(f"OC2 tree {tree.sha}: all {len(files)} configured portable unit files exist")
