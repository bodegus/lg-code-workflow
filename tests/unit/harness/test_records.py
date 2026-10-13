"""Cumulative SDK accounting and safe failure classification without live calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lgcw.harness.errors import (
    HarnessAuthError,
    HarnessError,
    HarnessOutputError,
    HarnessQuotaError,
    HarnessSessionLostError,
)
from lgcw.harness.records import TokenCounts, map_error, read_counts, turn_usage


@pytest.mark.unit
def test_usage_is_cumulative_delta_not_last_request() -> None:
    before = TokenCounts(
        input_tokens=100, cached_input_tokens=80, output_tokens=10, reasoning_output_tokens=2
    )
    after = TokenCounts(
        input_tokens=160, cached_input_tokens=100, output_tokens=35, reasoning_output_tokens=7
    )
    usage = turn_usage(before, after, context_window=1000, context_input_tokens=45)
    assert usage.input_tokens == 60
    assert usage.cached_input_tokens == 20
    assert usage.output_tokens == 25
    assert usage.reasoning_output_tokens == 5
    assert usage.context_input_tokens == 45


@pytest.mark.unit
def test_usage_refuses_decreasing_counters() -> None:
    before = TokenCounts(
        input_tokens=100, cached_input_tokens=80, output_tokens=10, reasoning_output_tokens=2
    )
    with pytest.raises(HarnessError, match="decreased"):
        turn_usage(
            before,
            before.model_copy(update={"input_tokens": 99}),
            context_window=None,
            context_input_tokens=45,
        )


@pytest.mark.unit
def test_read_counts_uses_latest_token_event(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    count = {
        "input_tokens": 30,
        "cached_input_tokens": 20,
        "output_tokens": 3,
        "reasoning_output_tokens": 1,
    }
    records = [
        {"type": "session_meta", "payload": {"id": "own"}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": count | {"total_tokens": 33}},
            },
        },
    ]
    path.write_text("\n".join(json.dumps(x) for x in records) + "\n")
    assert read_counts(path) == TokenCounts(**count)
    assert read_counts(None).input_tokens == 0


@pytest.mark.unit
def test_read_counts_does_not_invent_zero_after_malformed_evidence(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_text('{"type": "broken"')
    with pytest.raises(HarnessError, match="accounting"):
        read_counts(path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "message,kind",
    [
        ("unauthorized login expired", HarnessAuthError),
        ("Not logged in. Please log in.", HarnessAuthError),
        ("rate limit exceeded", HarnessQuotaError),
        ("usage limit exceeded", HarnessQuotaError),
        ("no rollout found for thread id fixture", HarnessSessionLostError),
        ("output schema validation failed", HarnessOutputError),
        ("transport closed", HarnessError),
        (
            "no rollout found for thread id 01a136e5-cab6-72d2-8429-9627b08dbc90",
            HarnessSessionLostError,
        ),
        ("transport closed on thread 01a136e5-cab6-72d2-8401-9627b08dbc90", HarnessError),
        ("HTTP 401", HarnessAuthError),
        ("HTTP 429", HarnessQuotaError),
    ],
)
def test_error_mapping_and_redaction(message: str, kind: type[HarnessError]) -> None:
    error = map_error(RuntimeError(message + " ghp_" + "x" * 36))
    assert type(error) is kind
    assert "ghp_" not in str(error)
