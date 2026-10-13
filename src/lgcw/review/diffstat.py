"""Parse git's numstat output without guessing ambiguous quoted paths."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import PurePosixPath

from lgcw.models.review import DiffStat, FileChange


def parse_numstat(text: str, excluded_globs: Sequence[str]) -> DiffStat:
    """Parse ordinary or NUL-delimited numstat, counting a binary change as one line.

    Raises:
        ValueError: Counts or paths are malformed; quoted paths need git's unambiguous -z form.
    """
    records = iter(text.split("\0") if "\0" in text else text.splitlines())
    files: list[FileChange] = []
    excluded: list[str] = []
    for record in records:
        if not record:
            continue
        parts = record.split("\t", 2)
        if len(parts) != 3:
            raise ValueError("invalid numstat record")
        added, deleted, path = parts
        if not path:
            try:
                old_path, path = next(records), next(records)
            except StopIteration:
                raise ValueError("incomplete NUL-delimited rename") from None
            if not old_path or not path:
                raise ValueError("empty rename path")
        elif "\0" not in text:
            if path.startswith('"'):
                raise ValueError("quoted numstat path requires -z")
            path = re.sub(r"\{[^{}]* => ([^{}]*)\}", r"\1", path)
            if " => " in path:
                path = path.split(" => ", 1)[1]
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts or str(parsed) == ".":
            raise ValueError("numstat path escapes repository")
        if added == deleted == "-":
            additions, deletions = 1, 0
        elif added.isdecimal() and deleted.isdecimal():
            additions, deletions = int(added), int(deleted)
        else:
            raise ValueError("invalid numstat line counts")
        if not any(parsed.full_match(pattern) for pattern in excluded_globs):
            files.append(FileChange(path=path, added=additions, deleted=deletions))
        else:
            excluded.append(path)
    return DiffStat(files=tuple(files), excluded_paths=tuple(excluded))
