"""Synthetic secrets are removed without touching ordinary version/log text."""

from __future__ import annotations

import base64
import json

import pytest

from lgcw.runlog import redact


def _synthetic_jwt() -> str:
    parts = [
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
        for value in ({"alg": "HS256"}, {"sub": "synthetic"})
    ]
    return ".".join([*parts, "x" * 24])


@pytest.mark.unit
@pytest.mark.parametrize(
    "synthetic",
    [
        "ghp_" + "A" * 36,
        "gho_" + "B" * 36,
        "ghu_" + "C" * 36,
        "ghs_" + "D" * 36,
        "ghr_" + "E" * 36,
        "github_pat_" + "F" * 60,
        "sk-" + "G" * 40,
        _synthetic_jwt(),
    ],
)
def test_token_patterns_redacted(synthetic: str) -> None:
    text = f"before {synthetic} after"
    cleaned = redact(text)
    assert synthetic not in cleaned
    assert cleaned.startswith("before ") and cleaned.endswith(" after")
    assert "REDACTED" in cleaned


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer synthetic-opaque-value\nnext line",
        "authorization: Basic synthetic-opaque-value\nnext line",
        "https://x-access-token:synthetic-opaque-value@github.test/repo",
    ],
)
def test_credential_context_redacted(text: str) -> None:
    assert "synthetic-opaque-value" not in redact(text)


@pytest.mark.unit
def test_ordinary_text_preserved() -> None:
    text = "v1.2.3: 12 tests passed; repo: example/sandbox"
    assert redact(text) == text


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        '"Authorization": "Bearer opaque-secret"',
        "'authorization': 'Basic b3BhcXVlLXNlY3JldA=='",
        "Authorization=Basic b3BhcXVlLXNlY3JldA==",
    ],
)
def test_authorization_dictionary_and_assignment_values_are_redacted(text: str) -> None:
    output = redact(text)
    assert "opaque-secret" not in output and "b3BhcXVlLXNlY3JldA==" not in output
    assert "[REDACTED]" in output
