"""Pure, redacted and byte-bounded failure evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence

from lgcw.ci.patterns import ERROR_START
from lgcw.ledger.markers import fingerprint
from lgcw.runlog import redact

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\d[T ][\d:.]+(?:Z|[+-]\d\d:\d\d)?\s*")
_PATH = re.compile(r"(?:[A-Za-z]:)?/(?:[^\s:]+/)*[^\s:]+")


def _clip(text: str, size: int) -> str:
    return text.encode()[: max(0, size)].decode(errors="ignore")


def trim_job_log(raw: str, failed_steps: Sequence[str], max_bytes: int = 8192) -> str:
    """Keep first-error context and the failing group's tail within a UTF-8 byte cap."""
    lines = [_TIMESTAMP.sub("", _ANSI.sub("", line)) for line in raw.lstrip("\ufeff").splitlines()]
    groups: list[tuple[str, list[str]]] = []
    active: list[str] = []
    name = ""
    for line in lines:
        if line.startswith("##[group]"):
            if active:
                groups.append((name, active))
            name, active = line.removeprefix("##[group]"), []
        elif line.startswith("##[endgroup]"):
            continue
        else:
            active.append(line)
    if active:
        groups.append((name, active))
    chosen = next(
        (
            body
            for name, body in groups
            if any(step.casefold() in name.casefold() for step in failed_steps)
        ),
        None,
    )
    if chosen is None or not any(ERROR_START.search(line) for line in chosen):
        chosen = next(
            (body for _, body in groups if any(ERROR_START.search(x) for x in body)), lines
        )
    error = next((i for i, line in enumerate(chosen) if ERROR_START.search(line)), 0)
    header = redact("Failed steps: " + ", ".join(failed_steps) + "\n")
    context = redact("\n".join(chosen[error : error + 60]))
    tail = redact("\n".join(chosen[-200:]))
    marker = "\n[... omitted ...]\n"
    complete = header + context + marker + tail
    if len(complete.encode()) <= max_bytes:
        return complete
    header = _clip(header, min(1024, max_bytes // 4))
    available = max(0, max_bytes - len(header.encode()) - len(marker.encode()))
    context = _clip(context, available // 2)
    tail_bytes = tail.encode()
    tail_size = available - len(context.encode())
    tail = tail_bytes[-tail_size:].decode(errors="ignore") if tail_size else ""
    return _clip(header + context + marker + tail, max_bytes)


def failure_fingerprint(workflow: str, job: str, step: str, first_error: str) -> str:
    """Normalize volatile error paths and numbers while retaining matrix identity."""
    error = re.sub(r"\d+", "#", _PATH.sub("<path>", first_error))
    return fingerprint(workflow, job, step, error)
