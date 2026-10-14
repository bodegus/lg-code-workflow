"""Conservative reviewed ranges from bounded local git diff evidence."""

from __future__ import annotations

import re

from lgcw.models.review import LineRange


def reviewed_ranges(diff: str) -> dict[str, tuple[LineRange, ...]]:
    """Read ordinary git paths and hunks; refuse quoted paths and incomplete hunks.

    Hunk counters distinguish actual file headers from added text resembling a header.
    Non-ASCII or control-character paths quoted by git require owner attention in Phase 1.
    """
    result: dict[str, list[LineRange]] = {}
    path: str | None = None
    old = new = 0
    for line in diff.splitlines():
        if old or new:
            if line.startswith("\\ No newline"):
                continue
            old -= int(line.startswith((" ", "-")))
            new -= int(line.startswith((" ", "+")))
            if old < 0 or new < 0 or not line.startswith((" ", "-", "+")):
                raise ValueError("invalid or truncated review hunk")
            continue
        if line.startswith("diff --git "):
            path = None
        elif line.startswith('+++ "'):
            raise ValueError("quoted review paths require owner inspection")
        elif line.startswith("--- a/"):
            path = line[6:].removesuffix("\t")
        elif line.startswith("+++ b/"):
            path = line[6:].removesuffix("\t")
        elif line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if match is None or path is None:
                raise ValueError("review hunk lacks a supported path/header")
            old, new = int(match[2] or 1), int(match[4] or 1)
            start = int(match[3])
            if new:
                result.setdefault(path, []).append(LineRange(start=start, end=start + new - 1))
    if old or new:
        raise ValueError("truncated review diff")
    return {key: tuple(value) for key, value in result.items()}
