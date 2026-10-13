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
    """Parse valid v1 markers, ignoring malformed or unknown records."""
    adapter = TypeAdapter(Marker)
    markers: list[Marker] = []
    for match in re.finditer(r"<!-- lgcw:v1 (\{.*?\}) -->", body, flags=re.DOTALL):
        try:
            markers.append(adapter.validate_python(json.loads(match.group(1))))
        except (ValueError, RecursionError):
            continue
    return markers


def strip_markers(body: str) -> str:
    """Remove marker blocks while preserving the surrounding text and whitespace."""
    return re.sub(r"<!-- lgcw:v1 (\{.*?\}) -->", "", body, flags=re.DOTALL)


def fingerprint(*parts: str) -> str:
    """Return a stable 16-character hash with unambiguous part boundaries."""
    payload = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]
