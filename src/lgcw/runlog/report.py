"""Render locally retained observations, measured usage and evidence gaps."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from lgcw.runlog.log import EventRecord, TurnRecord, _clean
from lgcw.runlog.redact import redact


def _escape(text: str) -> str:
    return (
        html.escape(text, quote=False)
        .replace("|", r"\|")
        .replace("`", "&#96;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _cell(value: object) -> str:
    return _escape(redact(str(value)))


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def render_report(run_dir: Path) -> str:
    """Render available run evidence; malformed records and unknown usage stay visible."""
    events: list[EventRecord] = []
    turns: list[tuple[Path, TurnRecord]] = []
    warnings: list[str] = []
    event_file = run_dir / "events.jsonl"
    if not _inside(event_file, run_dir):
        warnings.append("Ignored events.jsonl outside run directory.")
    elif event_file.exists():
        for number, line in enumerate(event_file.read_text().splitlines(), 1):
            try:
                events.append(EventRecord.model_validate_json(line))
            except ValueError:
                warnings.append(f"Ignored malformed event line {number}; inspect events.jsonl.")
    turn_dir = run_dir / "turns"
    if not _inside(turn_dir, run_dir):
        warnings.append("Ignored turns folder outside run directory.")
    for path in turn_dir.glob("*.json") if _inside(turn_dir, run_dir) else ():
        if not _inside(path, run_dir):
            warnings.append(f"Ignored turn {_cell(path.name)} outside run directory.")
            continue
        try:
            turns.append((path, TurnRecord.model_validate_json(path.read_text())))
        except ValueError:
            warnings.append(f"Skipped malformed turn {_cell(path.name)}.")
    turns.sort(key=lambda item: item[1].seq)
    outcome = next(
        (
            event.fields.get("outcome", "unknown")
            for event in reversed(events)
            if event.kind == "run_end"
        ),
        "unknown",
    )
    last_start = max((i for i, event in enumerate(events) if event.kind == "run_start"), default=-1)
    last_end = max((i for i, event in enumerate(events) if event.kind == "run_end"), default=-1)
    if last_start > last_end:
        outcome = "incomplete"
        warnings.append("Latest invocation has no run_end record; execution status is unproven.")
    lines = ["# Run report", "", f"Outcome: {_cell(outcome)}", "", "## Timeline", ""]
    if events:
        lines.extend(
            (
                "| Time | Node | Event | Duration (s) | Attempt | Evidence |",
                "|---|---|---|---:|---:|---|",
            )
        )
        for event in events:
            details = json.dumps(_clean(event.fields), ensure_ascii=False, sort_keys=True)
            if len(details) > 1000:
                details = details[:1000] + " … (see events.jsonl)"
            lines.append(
                f"| {_cell(event.timestamp.isoformat())} | {_cell(event.node or '—')} | "
                f"{_cell(event.kind)} | {_cell(event.fields.get('duration_s', '—'))} | "
                f"{_cell(event.fields.get('attempt', '—'))} | {_escape(details)} |"
            )
        durations: dict[str, float] = {}
        for event in events:
            duration = event.fields.get("duration_s")
            if event.kind == "node_end" and event.node and isinstance(duration, (int, float)):
                durations[event.node] = durations.get(event.node, 0) + duration
        if durations:
            lines.extend(("", "| Step | Recorded seconds |", "|---|---:|"))
            lines.extend(
                f"| {_cell(node)} | {seconds:g} |" for node, seconds in sorted(durations.items())
            )
    else:
        lines.append("No events recorded.")
    lines.extend(("", "## Agent turns", ""))
    totals = [0, 0, 0, 0]
    unknown = 0
    if turns:
        lines.extend(
            (
                "| Seq | Role | Session | Input | Cached input | Output | Reasoning output | "
                "Context window | Seconds | Error | Raw |",
                "|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|",
            )
        )
        for path, turn in turns:
            raw = f"[turn]({quote(path.relative_to(run_dir).as_posix(), safe='/')})"
            if turn.outcome is None:
                unknown += 1
                lines.append(
                    f"| {turn.seq} | {turn.role} | — | — | — | — | — | — | — | "
                    f"{_cell(turn.error or 'unknown')} | {raw} |"
                )
            else:
                measured = turn.outcome
                usage = measured.usage
                counts = [
                    usage.input_tokens,
                    usage.cached_input_tokens,
                    usage.output_tokens,
                    usage.reasoning_output_tokens,
                ]
                totals = [total + count for total, count in zip(totals, counts, strict=True)]
                lines.append(
                    f"| {turn.seq} | {turn.role} | {_cell(measured.session_id)} | "
                    + " | ".join(str(count) for count in counts)
                    + f" | {usage.context_window or '—'} | {measured.duration_s:g} | "
                    + f"{_cell(turn.error or '—')} | {raw} |"
                )
        lines.extend(
            (
                "",
                "| Usage | Input | Cached input | Output | Reasoning output |",
                "|---|---:|---:|---:|---:|",
                "| Total known usage | " + " | ".join(str(count) for count in totals) + " |",
                "",
                "Input includes cached tokens. Cached and reasoning tokens "
                "are reported separately, not added twice.",
            )
        )
        if unknown:
            lines.append(
                f"Usage unavailable for {unknown} turn(s); totals cover measured turns only."
            )
    else:
        lines.append("No agent turns recorded.")
    for title, kinds in (
        ("Loop rounds", {"loop_round", "ledger_counts"}),
        ("CI decisions", {"ci_decision"}),
        ("Findings and dispositions", {"finding", "disposition"}),
    ):
        lines.extend(("", f"## {title}", ""))
        selected = [event for event in events if event.kind in kinds]
        if selected:
            lines.extend(("| Event | Node | Recorded evidence |", "|---|---|---|"))
            for event in selected:
                fields = json.dumps(_clean(event.fields), ensure_ascii=False, sort_keys=True)
                lines.append(
                    f"| {_cell(event.kind)} | {_cell(event.node or '—')} | {_escape(fields)} |"
                )
        else:
            lines.append("No observations recorded.")
    if warnings:
        lines.extend(("", "## Evidence warnings", ""))
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(("", "Raw controller evidence: [events.jsonl](events.jsonl).", ""))
    return "\n".join(lines)
