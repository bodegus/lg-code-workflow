"""Typed local evidence with semantic redaction before JSON serialization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, JsonValue

from lgcw.clock import Clock, SystemClock
from lgcw.ledger.markers import parse_markers, render_marker
from lgcw.models.base import Strict
from lgcw.models.harness import Role, TurnInput, TurnOutcome, Usage
from lgcw.runlog.redact import redact

_CREDENTIAL_KEYS = frozenset(
    {
        "authorization",
        "gh_token",
        "github_token",
        "openai_api_key",
        "codex_api_key",
        "token",
        "api_key",
        "access_token",
        "refresh_token",
        "id_token",
        "password",
        "client_secret",
    }
)


class EventRecord(Strict):
    """One timestamped controller observation, never a source of routing state."""

    timestamp: datetime
    kind: str
    node: str | None
    fields: dict[str, JsonValue]


class LoggedOutcome(Strict):
    """A validated turn's JSON output and measured usage."""

    session_id: str
    output: JsonValue
    usage: Usage
    duration_s: float = Field(ge=0)
    rollout_path: Path | None


class TurnRecord(Strict):
    """Prompt, result or error for one local evidence sequence."""

    timestamp: datetime
    seq: int = Field(ge=1)
    role: Role
    turn: TurnInput
    outcome: LoggedOutcome | None
    error: str | None


def _clean(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {
            redact(key): "[REDACTED]" if key.casefold() in _CREDENTIAL_KEYS else _clean(item)
            for key, item in value.items()
        }
    return value


def _json(model: BaseModel) -> str:
    return json.dumps(
        _clean(model.model_dump(mode="json")),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def redact_data(value: JsonValue) -> JsonValue:
    """Redact nested values before a structured record is serialized to any artifact."""
    return _clean(value)


class RunLog:
    """Append events and retain redacted artifacts without replacing different evidence."""

    def __init__(self, run_dir: Path, *, clock: Clock | None = None) -> None:
        self.run_dir = run_dir.absolute()
        self._clock = clock if clock is not None else SystemClock()

    def _target(self, relative: str) -> Path:
        rel = PurePosixPath(relative)
        if (
            rel.is_absolute()
            or ".." in rel.parts
            or not rel.parts
            or rel.parts[0] in {"repo", "mirrors", "codex"}
            or rel.parts[0].startswith("review-")
        ):
            raise ValueError("artifact path must stay inside the run's evidence folders")
        path = self.run_dir.joinpath(*rel.parts)
        if not path.resolve().is_relative_to(self.run_dir.resolve()):
            raise ValueError("artifact symlink escapes run directory")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def _atomic(self, path: Path, content: str, *, replace: bool = False) -> Path:
        if path.exists() and not replace:
            if path.read_text() == content:
                return path
            raise FileExistsError("different evidence already exists at artifact path")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path

    def event(self, kind: str, *, node: str | None = None, **fields: JsonValue) -> None:
        """Append one valid JSON line after recursively redacting individual values."""
        record = EventRecord(timestamp=self._clock.now(), kind=kind, node=node, fields=fields)
        content = _json(record) + "\n"
        path = self._target("events.jsonl")
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)

    def next_turn_seq(self) -> int:
        """Allocate after every retained turn artifact across roles and process restarts.

        This selects an evidence filename, not a workflow routing counter. The caller owns
        the per-issue execution lock; turn() still refuses any existing sequence.
        """
        folder = self._target("turns/.sequence").parent
        sequences = [
            int(match.group(1))
            for path in folder.glob("*.json")
            if (match := re.fullmatch(r"(\d+)-(builder|reviewer|verifier)\.json", path.name))
        ]
        return max(sequences, default=0) + 1

    def turn(
        self,
        seq: int,
        role: Role,
        turn: TurnInput,
        outcome: TurnOutcome[Any] | None,
        error: str | None,
    ) -> Path:
        """Retain a complete turn or an explicit unknown-usage error without overwriting history."""
        record = TurnRecord(
            timestamp=self._clock.now(),
            seq=seq,
            role=role,
            turn=turn,
            outcome=LoggedOutcome.model_validate(outcome.model_dump(mode="json"))
            if outcome
            else None,
            error=error,
        )
        path = self._target(f"turns/{seq:04d}-{role}.json")
        if path.exists():
            raise FileExistsError("turn sequence already recorded")
        return self._atomic(path, _json(record) + "\n")

    def artifact(self, rel: str, content: str) -> Path:
        """Write redacted text evidence; only the derived report view may be replaced."""
        if rel == "report.md":
            generated = self._report_text()
            if content != generated:
                raise ValueError("report.md is reserved for the generated evidence view")
            return self._atomic(self._target(rel), generated, replace=True)
        return self._atomic(self._target(rel), redact(content))

    def _report_text(self) -> str:
        from lgcw.runlog.report import render_report

        return render_report(self.run_dir)

    def write_report(self) -> Path:
        """Regenerate the semantically redacted report without redacting encoded cells again."""
        return self._atomic(self._target("report.md"), self._report_text(), replace=True)

    def posted(self, kind: str, body: str, ids: Mapping[str, str | int]) -> Path:
        """Retain a redacted posted body with independently encoded ID metadata."""
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", kind):
            raise ValueError("invalid posted artifact kind")
        folder = self.run_dir / "github"
        values: dict[str, JsonValue] = dict(ids)
        metadata = json.dumps(_clean(values), ensure_ascii=False, indent=2, sort_keys=True).replace(
            "`", r"\u0060"
        )
        records = parse_markers(body)
        if records:
            record = records[0]
            clean_record = type(record).model_validate(_clean(record.model_dump(mode="json")))
            prefix = body[: body.rfind("<!-- lgcw:v1 ")]
            clean_body = redact(prefix) + render_marker(clean_record)
        else:
            clean_body = redact(body)
        content = f"```json\n{metadata}\n```\n\n{clean_body}"
        identity = hashlib.sha256(content.encode()).hexdigest()[:16]
        for path in folder.glob(f"*-{kind}-{identity}.md"):
            return self._atomic(path, content)
        existing = [
            int(match.group(1))
            for path in folder.glob("*.md")
            if (match := re.match(r"(\d+)-", path.name))
        ]
        sequence = max(existing, default=0) + 1
        return self._atomic(self._target(f"github/{sequence:04d}-{kind}-{identity}.md"), content)
