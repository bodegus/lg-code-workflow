"""Check reviewer evidence with lexical paths, reviewed ranges and deduplication."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from lgcw.ledger.markers import fingerprint
from lgcw.models.review import (
    GatedFinding,
    GateResult,
    LensVerdict,
    LevelDecision,
    LineRange,
)


def finding_id(path: str, title: str, category: str) -> str:
    """Identify a defect independently of priority tags, whitespace and title case."""
    title = re.sub(r"^\s*\[P[0-3]\]\s*", "", title, flags=re.I)
    return fingerprint(path, " ".join(title.casefold().split()), category.strip().casefold())


def gate_findings(
    results: Sequence[LensVerdict],
    level: LevelDecision,
    ranges: Mapping[str, Sequence[LineRange]],
    repo_root: Path,
    known_ids: Collection[str],
) -> GateResult:
    """Admit findings only on reviewed lines; return every rejection with its reason."""
    if not repo_root.is_absolute() or ".." in repo_root.parts:
        raise ValueError("review checkout root must be an absolute lexical path")
    blocking: list[GatedFinding] = []
    advisory: list[GatedFinding] = []
    dropped: list[GatedFinding] = []
    seen = set(known_ids)
    candidates = sorted(
        ((result.lens, finding) for result in results for finding in result.verdict.findings),
        key=lambda item: (
            item[1].priority,
            -item[1].confidence_score,
            item[0],
            item[1].code_location.absolute_file_path,
            item[1].title,
        ),
    )
    for lens, finding in candidates:
        location = finding.code_location
        absolute = Path(location.absolute_file_path)
        reason = ""
        path = str(absolute)
        if (
            not absolute.is_absolute()
            or ".." in absolute.parts
            or not absolute.is_relative_to(repo_root)
        ):
            reason = "location is outside the checkout or contains parent traversal"
        else:
            path = absolute.relative_to(repo_root).as_posix()
        identity = finding_id(path, finding.title, finding.category)
        if not reason and lens not in level.lenses:
            reason = "lens was not requested"
        if not reason and not any(
            reviewed.start <= location.line_range.start and location.line_range.end <= reviewed.end
            for reviewed in ranges.get(path, ())
        ):
            reason = "finding is outside reviewed lines"
        if not reason and identity in seen:
            reason = "finding was already reported"
        if reason:
            dropped.append(
                GatedFinding(
                    id=identity,
                    lens=lens,
                    path=path,
                    finding=finding,
                    blocking=False,
                    reason=reason,
                )
            )
            continue
        seen.add(identity)
        priority_blocks = finding.priority <= 1 or (
            level.level == "deep"
            and finding.priority == 2
            and finding.category.strip().casefold() == "security"
        )
        blocks = (
            level.level != "none"
            and priority_blocks
            and (level.level != "light" or finding.confidence_score >= 0.7)
        )
        item = GatedFinding(
            id=identity,
            lens=lens,
            path=path,
            finding=finding,
            blocking=blocks,
            reason="blocking candidate; verification required"
            if blocks and level.level in {"standard", "deep"}
            else "blocking priority/confidence"
            if blocks
            else "advisory under review policy",
        )
        (blocking if blocks else advisory).append(item)
    return GateResult(blocking=tuple(blocking), nonblocking=tuple(advisory), dropped=tuple(dropped))
