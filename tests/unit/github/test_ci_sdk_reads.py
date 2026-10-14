"""Pinned SDK read boundaries over a synthetic in-memory HTTP transport."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from githubkit import GitHub

from lgcw.github.client import download_job_log, required_policy
from lgcw.github.port import CiEvidenceLimitError, RequiredPolicyError


class BigLog(httpx.AsyncByteStream):
    """A finite lazy body that exposes whether the reader bounded its download."""

    def __init__(self) -> None:
        self.chunks = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(4096):
            self.chunks += 1
            yield b"x" * 16384

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.unit
@pytest.mark.parametrize("status", [404, 409, 410])
async def test_missing_job_log_keeps_available_evidence(status: int) -> None:
    sdk = GitHub(
        "unit-synthetic",
        auto_retry=False,
        http_cache=False,
        async_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status, json={"message": "expired unit log"}, request=request
            )
        ),
    )
    text = await download_job_log(sdk, "example", "sandbox", 1)
    assert "unavailable" in text and "annotations" in text


@pytest.mark.unit
async def test_streaming_log_cap_closes_response_before_full_body() -> None:
    body = BigLog()
    sdk = GitHub(
        "unit-synthetic",
        auto_retry=False,
        http_cache=False,
        async_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=body, request=request)
        ),
    )
    with pytest.raises(CiEvidenceLimitError, match="log.*limit"):
        await download_job_log(sdk, "example", "sandbox", 1)
    assert body.closed and body.chunks < 4096


@pytest.mark.unit
@pytest.mark.parametrize("protected", [False, True])
async def test_classic_404_cross_checks_branch_protection(protected: bool) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if "/rules/branches/" in request.url.path:
            return httpx.Response(200, json=[], request=request)
        if request.url.path.endswith("/required_status_checks"):
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path.endswith("/branches/main"):
            # This endpoint uses a typed complete branch payload; helper reads protected only.
            return httpx.Response(
                200,
                json={
                    "protected": protected,
                    "protection": {
                        "enabled": protected,
                        "required_status_checks": {
                            "enforcement_level": "everyone" if protected else "off",
                            "checks": [{"context": "test"}] if protected else [],
                            "contexts": ["test"] if protected else [],
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(str(request.url))

    sdk = GitHub(
        "unit-synthetic",
        auto_retry=False,
        http_cache=False,
        async_transport=httpx.MockTransport(respond),
    )
    if protected:
        with pytest.raises(RequiredPolicyError, match="protected"):
            await required_policy(sdk, "example", "sandbox", "main")
    else:
        assert await required_policy(sdk, "example", "sandbox", "main") == ()


@pytest.mark.unit
async def test_paginated_observation_stops_at_cap() -> None:
    from lgcw.github.client import bounded_rows

    consumed: list[int] = []

    async def rows() -> AsyncIterator[int]:
        for index in range(1000):
            consumed.append(index)
            yield index

    with pytest.raises(CiEvidenceLimitError, match="run.*limit"):
        await bounded_rows(rows(), 100, "run")
    assert len(consumed) == 101


@pytest.mark.unit
async def test_startup_error_hydrated_from_check_suite() -> None:
    from lgcw.github.client import execution_from_rest

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/check-suites/12/check-runs")
        return httpx.Response(
            200,
            json={
                "total_count": 1,
                "check_runs": [
                    {
                        "output": {
                            "title": "Invalid workflow file",
                            "summary": "broken.yml line 4 invalid syntax",
                            "text": None,
                        }
                    }
                ],
            },
            request=request,
        )

    sdk = GitHub(
        "unit-synthetic",
        auto_retry=False,
        http_cache=False,
        async_transport=httpx.MockTransport(respond),
    )
    data = {
        "id": 1,
        "name": "CI",
        "path": ".github/workflows/broken.yml",
        "event": "pull_request",
        "head_branch": "lgcw/issue-1",
        "head_sha": "a" * 40,
        "head_repository": {"full_name": "example/sandbox"},
        "pull_requests": [{"number": 100}],
        "status": "completed",
        "conclusion": "startup_failure",
        "run_attempt": 1,
        "check_suite_id": 12,
    }
    result = await execution_from_rest(sdk, "example", "sandbox", data)
    assert "Invalid workflow file" in result.startup_error
    assert "line 4 invalid syntax" in result.startup_error


@pytest.mark.unit
@pytest.mark.parametrize(
    ("protection", "allowed"),
    [
        ({"enabled": False}, True),
        (
            {
                "enabled": False,
                "required_status_checks": {
                    "enforcement_level": "off",
                    "checks": [],
                    "contexts": [],
                },
            },
            True,
        ),
        (
            {"required_status_checks": {"enforcement_level": "off", "checks": [], "contexts": []}},
            True,
        ),
        (
            {
                "enabled": True,
                "required_status_checks": {
                    "enforcement_level": "everyone",
                    "checks": [{"context": "test"}],
                    "contexts": ["test"],
                },
            },
            False,
        ),
        (
            {
                "required_status_checks": {
                    "enforcement_level": "non_admins",
                    "checks": [],
                    "contexts": [],
                }
            },
            False,
        ),
        (None, False),
    ],
)
async def test_classic_404_uses_explicit_classic_state(
    protection: dict[str, object] | None, allowed: bool
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if "/rules/branches/" in request.url.path:
            return httpx.Response(200, json=[], request=request)
        if request.url.path.endswith("/required_status_checks"):
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path.endswith("/branches/main"):
            data: dict[str, object] = {"protected": True}
            if protection is not None:
                data["protection"] = protection
            return httpx.Response(200, json=data, request=request)
        raise AssertionError(str(request.url))

    sdk = GitHub(
        "unit-synthetic",
        auto_retry=False,
        http_cache=False,
        async_transport=httpx.MockTransport(respond),
    )
    if allowed:
        assert await required_policy(sdk, "example", "sandbox", "main") == ()
    else:
        with pytest.raises(RequiredPolicyError):
            await required_policy(sdk, "example", "sandbox", "main")
