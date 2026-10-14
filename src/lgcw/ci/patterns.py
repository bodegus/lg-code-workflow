"""Auditable signal patterns for the CI decision table."""

from __future__ import annotations

import re

TIMEOUT_ANNOTATION = re.compile(
    r"exceeded (?:the )?maximum execution time|has timed out|timed_out", re.I
)
INFRA_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"runner.*(?:lost|offline|not acquired|disconnected)|lost.*runner",
        r"(?:action|image).*download.*(?:fail|error)|failed to download.*(?:action|image)",
    )
)
RESOURCE_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bENOSPC\b|no space left on device",
        r"out of memory|\bOOM\b",
        r"exit(?: code)?[: ]+137\b",
    )
)
ERROR_START = re.compile(
    r"##\[error\]|Traceback|\bERROR\b|AssertionError|error:|\bFAILED\b|fatal:", re.I
)
