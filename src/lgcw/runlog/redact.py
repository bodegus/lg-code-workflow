"""Remove credential-shaped values before logs or artifacts leave plain code."""

from __future__ import annotations

import re


def redact(text: str) -> str:
    """Mask GitHub/OpenAI tokens, JWTs and explicit credential-bearing contexts."""
    text = re.sub(r"(?im)(authorization\s*:\s*)[^\r\n]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(x-access-token:)[^@\s]+(@)", r"\1[REDACTED]\2", text)
    text = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-[A-Za-z0-9_-]{16,})",
        "[REDACTED]",
        text,
    )
    return re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", text)
