"""Pure accounting and error translation for the official SDK boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path

from openai_codex.generated.v2_all import CodexErrorInfoValue, TurnError
from pydantic import Field, ValidationError

from lgcw.harness.errors import (
    HarnessAuthError,
    HarnessError,
    HarnessOutputError,
    HarnessQuotaError,
    HarnessSessionLostError,
)
from lgcw.models.base import Strict
from lgcw.models.harness import Usage


class TokenCounts(Strict):
    """Measured cumulative counters; never a model estimate."""

    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_output_tokens: int = Field(ge=0)


def read_counts(path: Path | None) -> TokenCounts:
    """Read the last durable token event before a resumed turn, failing on corrupt evidence."""
    counts = TokenCounts(
        input_tokens=0, cached_input_tokens=0, output_tokens=0, reasoning_output_tokens=0
    )
    if path is None:
        return counts
    try:
        with path.open() as stream:
            for line in stream:
                record = json.loads(line)
                if record.get("type") != "event_msg":
                    continue
                payload = record.get("payload", {})
                if payload.get("type") != "token_count" or payload.get("info") is None:
                    continue
                total = payload["info"]["total_token_usage"]
                counts = TokenCounts.model_validate(
                    {key: total[key] for key in TokenCounts.model_fields}
                )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HarnessError("cannot read durable token accounting") from exc
    return counts


def turn_usage(
    before: TokenCounts,
    after: TokenCounts,
    *,
    context_window: int | None,
    context_input_tokens: int,
) -> Usage:
    """Subtract cumulative billed counters, keeping the latest context size separately."""
    delta = {key: getattr(after, key) - getattr(before, key) for key in TokenCounts.model_fields}
    if any(value < 0 for value in delta.values()):
        raise HarnessError("cumulative token accounting decreased")
    return Usage.model_validate(
        delta | {"context_window": context_window, "context_input_tokens": context_input_tokens}
    )


def map_error(error: Exception) -> HarnessError:
    """Classify SDK failures without retrying a paid turn or exposing credentials."""
    if isinstance(error, HarnessError):
        return error
    if isinstance(error, ValidationError):
        return HarnessOutputError("agent output did not match the required schema")
    message = str(error)
    lowered = message.lower()
    kind: type[HarnessError] = HarnessError
    if any(
        word in lowered
        for word in ("unauthorized", "authentication", "login expired", "not logged in")
    ) or re.search(r"\b401\b", lowered):
        kind = HarnessAuthError
    elif any(
        word in lowered
        for word in (
            "rate limit",
            "rate_limit",
            "ratelimitexceeded",
            "usage limit",
            "usage_limit",
            "usagelimitexceeded",
            "quota",
        )
    ) or re.search(r"\b429\b", lowered):
        kind = HarnessQuotaError
    elif any(word in lowered for word in ("no rollout found", "thread not found", "session lost")):
        kind = HarnessSessionLostError
    elif "output schema" in lowered or "output_schema" in lowered:
        kind = HarnessOutputError
    return kind(message or type(error).__name__)


def map_turn_error(error: TurnError) -> HarnessError:
    """Prefer the SDK's typed error code over incidental words in server prose."""
    info = error.codex_error_info
    if info is None:
        return map_error(RuntimeError(error.message))
    if info.root == CodexErrorInfoValue.unauthorized:
        return HarnessAuthError(error.message)
    if info.root in (
        CodexErrorInfoValue.usage_limit_exceeded,
        CodexErrorInfoValue.rate_limit_exceeded,
    ):
        return HarnessQuotaError(error.message)
    return HarnessError(error.message)
