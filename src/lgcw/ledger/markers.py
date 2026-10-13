"""Safe hidden markers and deterministic fingerprints."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import TypeAdapter

from lgcw.models.ledger import Marker


def render_marker(marker: Marker) -> str:
    """Render compact JSON without a possible HTML-comment terminator in its data."""
    payload = json.dumps(marker.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=True)
    payload = payload.replace("--", r"-\u002d")
    return "<!-- lgcw:v1 " + payload + " -->"


def parse_markers(body: str) -> list[Marker]:
    """Accept one complete trailing record; quoted/multiple records are not facts."""
    prefix = "<!-- lgcw:v1 "
    start = body.rfind(prefix)
    if start < 0:
        return []
    pattern = r"\{[^\n]*\} -->\s*\Z"
    trailing = re.fullmatch(pattern, body[start + len(prefix) :])
    # An incomplete earlier prefix is data, but any earlier complete marker is ambiguous.
    if trailing is None or re.search(r"<!-- lgcw:v1 \{[^\n]*\} -->", body[:start]):
        return []
    payload = body[start + len(prefix) :].rstrip().removesuffix(" -->")
    try:
        return [TypeAdapter(Marker).validate_python(json.loads(payload))]
    except (ValueError, RecursionError):
        return []


def strip_markers(body: str) -> str:
    """Remove marker blocks while preserving the surrounding text and whitespace."""
    return re.sub(r"<!-- lgcw:v1 (\{.*?\}) -->", "", body, flags=re.DOTALL)


def fingerprint(*parts: str) -> str:
    """Return a stable 16-character hash with unambiguous part boundaries."""
    payload = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]
