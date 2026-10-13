"""Opt-in GitHub contract on an isolated sandbox issue and non-default branch."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from githubkit import GitHub
from githubkit.auth import TokenAuthStrategy
from githubkit.exception import RequestFailed

from lgcw.github.client import GitHubClient
from lgcw.github.token import GhCliTokenProvider
from lgcw.live import require_live
from lgcw.models.base import Strict
from lgcw.models.issue import IssueRef
from tests.contract.github_scenarios import (
    GitHubContractTarget,
    scenario_draft_pr_then_ready,
    scenario_issue_comments_round_trip,
    scenario_review_thread_reply_and_resolve,
)

if TYPE_CHECKING:
    from githubkit_schemas.v2026_03_10.models import PullRequestSimple


class ContractReceipt(Strict):
    """Non-secret service identities and cleanup results from this one test."""

    repo: str
    branch: str
    issue_url: str | None
    issue_number: int | None
    pr_url: str | None
    head_sha: str | None
    failure_class: str | None
    closed_prs: tuple[int, ...]
    issue_closed: bool
    branch_deleted: bool


def _save(path: Path, receipt: ContractReceipt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(receipt.model_dump_json(indent=2) + "\n")
    temporary.replace(path)


@pytest.mark.live
async def test_github_contract(tmp_path: Path) -> None:
    """Run the shared scenarios, retain receipts, then close only this fixture's artifacts."""
    require_live("GitHub contract fixture", False)
    provider = GhCliTokenProvider()
    client = GitHubClient(provider)
    sdk: GitHub[TokenAuthStrategy] = GitHub(
        provider.token(), auto_retry=False, http_cache=False, timeout=30.0
    )
    owner, name = "bodegus", "family-calendar"
    repo = f"{owner}/{name}"
    nonce = uuid4().hex
    branch = f"lgcw-contract-{nonce}"
    fixture_path = f"lgcw-contract-{nonce}.txt"
    receipt_path = Path(os.environ.get("LGCW_LIVE_RECEIPT", str(tmp_path / "receipt.json")))
    receipt = ContractReceipt(
        repo=repo,
        branch=branch,
        issue_url=None,
        issue_number=None,
        pr_url=None,
        head_sha=None,
        failure_class=None,
        closed_prs=(),
        issue_closed=False,
        branch_deleted=False,
    )
    _save(receipt_path, receipt)
    async with sdk:
        try:
            base_ref = (await sdk.rest.git.async_get_ref(owner, name, "heads/main")).parsed_data
            base = (
                await sdk.rest.git.async_get_commit(owner, name, base_ref.object_.sha)
            ).parsed_data
            tree = (
                await sdk.rest.git.async_create_tree(
                    owner,
                    name,
                    data={
                        "base_tree": base.tree.sha,
                        "tree": [
                            {
                                "path": fixture_path,
                                "mode": "100644",
                                "type": "blob",
                                "content": "Synthetic lgcw contract fixture.\n",
                            }
                        ],
                    },
                )
            ).parsed_data
            await asyncio.sleep(1)
            commit = (
                await sdk.rest.git.async_create_commit(
                    owner,
                    name,
                    data={
                        "message": f"test: lgcw contract {nonce}",
                        "tree": tree.sha,
                        "parents": [base.sha],
                    },
                )
            ).parsed_data
            receipt = receipt.model_copy(update={"head_sha": commit.sha})
            _save(receipt_path, receipt)
            await asyncio.sleep(1)
            await sdk.rest.git.async_create_ref(
                owner,
                name,
                data={
                    "ref": f"refs/heads/{branch}",
                    "sha": commit.sha,
                },
            )
            await asyncio.sleep(1)
            issue = (
                await sdk.rest.issues.async_create(
                    owner,
                    name,
                    data={
                        "title": f"lgcw live contract {nonce}",
                        "body": (
                            "Isolated live adapter fixture; no merge.\n\n"
                            "## Done when\n- Contract passes.\n-builder"
                        ),
                    },
                )
            ).parsed_data
            receipt = receipt.model_copy(
                update={"issue_number": issue.number, "issue_url": issue.html_url}
            )
            _save(receipt_path, receipt)
            await asyncio.sleep(1)
            target = GitHubContractTarget(
                issue=IssueRef(repo=repo, number=issue.number),
                branch=branch,
                base="main",
                head_sha=commit.sha,
                path=fixture_path,
                line=1,
            )
            assert await client.branch_head(repo, branch) == commit.sha
            await scenario_issue_comments_round_trip(client, target)
            pr = await scenario_draft_pr_then_ready(client, target)
            document = await client.get_pr_document(repo, pr.number)
            assert document.head_sha == commit.sha and document.head_ref == branch
            assert document.author == await client.viewer_login()
            assert document.body == "Contract only; no merge.\n-builder"
            receipt = receipt.model_copy(update={"pr_url": pr.url})
            _save(receipt_path, receipt)
            await scenario_review_thread_reply_and_resolve(client, target, pr)
            empty_id = await client.create_review(
                repo, pr.number, commit.sha, "Empty review receipt\n-builder", []
            )
            reviews = await client.list_pr_reviews(repo, pr.number)
            assert any(
                review.id == empty_id and review.body == "Empty review receipt\n-builder"
                for review in reviews
            )
            await client.update_pr_body(repo, pr.number, "Contract complete; no merge.\n-builder")
            assert not (await client.get_pr(repo, pr.number)).is_draft
        except BaseException as error:
            receipt = receipt.model_copy(update={"failure_class": type(error).__name__})
            _save(receipt_path, receipt)
            raise
        finally:
            # REST cleanup can still find the fixture if a GraphQL read after PR creation failed.
            # No mutation is retried; completed effects remain in the receipt and on GitHub.
            closed: list[int] = []
            fixtures: AsyncIterator[PullRequestSimple] = sdk.rest.paginate(
                sdk.rest.pulls.async_list,
                owner=owner,
                repo=name,
                state="open",
                head=f"{owner}:{branch}",
                per_page=100,
            )
            async for fixture_pr in fixtures:
                if fixture_pr.title != "lgcw contract fixture":
                    raise RuntimeError("Unexpected PR on fixture branch; preserving it")
                await asyncio.sleep(1)
                await sdk.rest.pulls.async_update(
                    owner, name, fixture_pr.number, data={"state": "closed"}
                )
                closed.append(fixture_pr.number)
                receipt = receipt.model_copy(
                    update={
                        "closed_prs": tuple(closed),
                        "pr_url": fixture_pr.html_url,
                    }
                )
                _save(receipt_path, receipt)
            if receipt.issue_number is not None:
                await asyncio.sleep(1)
                await sdk.rest.issues.async_update(
                    owner, name, receipt.issue_number, data={"state": "closed"}
                )
                receipt = receipt.model_copy(update={"issue_closed": True})
                _save(receipt_path, receipt)
            if receipt.head_sha is not None:
                try:
                    observed = (
                        await sdk.rest.git.async_get_ref(owner, name, f"heads/{branch}")
                    ).parsed_data
                except RequestFailed as error:
                    if error.response.status_code != 404:
                        raise
                else:
                    if observed.object_.sha != receipt.head_sha:
                        raise RuntimeError(
                            "Fixture branch head changed; preserving another actor's commit"
                        )
                    await asyncio.sleep(1)
                    await sdk.rest.git.async_delete_ref(owner, name, f"heads/{branch}")
                    receipt = receipt.model_copy(update={"branch_deleted": True})
                    _save(receipt_path, receipt)

            if receipt.closed_prs:
                closed_pr = await client.find_pr(repo, branch)
                assert closed_pr is not None and closed_pr.number in receipt.closed_prs
                assert closed_pr.state == "CLOSED"
                assert await client.find_open_pr(repo, branch) is None
