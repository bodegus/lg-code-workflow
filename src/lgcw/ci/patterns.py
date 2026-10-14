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
SETUP_STEP = re.compile(
    r"^(?:setup|set up job|setup job|install dependencies|checkout(?: code)?|"
    r"(?:run )?actions/(?:checkout|setup-[a-z0-9-]+|cache)@[^ ]+|"
    r"setup (?:node|python|java|go)|restore (?:dependencies|cache)|cache dependencies)$",
    re.I,
)
NETWORK_ERROR = re.compile(
    r"could not resolve host|connection (?:reset|refused)|network (?:error|unreachable)|"
    r"rate limit|HTTP (?:429|502|503|504)",
    re.I,
)
