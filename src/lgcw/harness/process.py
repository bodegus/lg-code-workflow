"""Bounded cleanup of the owned app-server and its descendants, including detached groups."""

from __future__ import annotations

import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

from lgcw.git.run import run_process


async def _parents(cwd: Path) -> dict[int, int]:
    result = await run_process(("/bin/ps", "-axo", "pid=,ppid="), cwd=cwd, timeout_s=1)
    if result.code != 0:
        raise RuntimeError("cannot inspect owned runtime process ancestry")
    return {
        int(parts[0]): int(parts[1])
        for line in result.out.splitlines()
        if len(parts := line.split()) == 2
    }


def _owned(parents: dict[int, int], root: int) -> set[int]:
    descendants = {root}
    while True:
        found = {pid for pid, parent in parents.items() if parent in descendants}
        if found <= descendants:
            return descendants
        descendants.update(found)


def _signal(pid: int, sig: signal.Signals) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


async def terminate_runtime(
    pidfile: Path, *, inspect_parents: Callable[[Path], Awaitable[dict[int, int]]] = _parents
) -> None:
    """Freeze then kill only a verified direct child runtime and its process descendants.

    A detached shell can leave its process group while still being a descendant. Stop parents
    before collecting again so they cannot race cleanup by spawning new children. No command
    lines or environments are inspected. Never signal self, an ancestor or a foreign parent.
    """
    if not pidfile.exists():
        return
    root = int(pidfile.read_text().strip())
    if root <= 1 or root == os.getpid():
        raise ValueError("runtime PID is not owned")
    parents = await inspect_parents(pidfile.parent)
    if root not in parents:
        pidfile.unlink(missing_ok=True)
        return
    if parents[root] != os.getpid():
        raise ValueError("runtime PID is not an owned direct child")
    stopped: set[int] = set()
    try:
        for _ in range(3):
            descendants = _owned(parents, root)
            fresh = descendants - stopped
            if not fresh:
                break
            # Freeze root first; subsequent passes catch children spawned by a running child.
            for pid in [root, *sorted(fresh - {root})]:
                _signal(pid, signal.SIGSTOP)
                stopped.add(pid)
            parents = await inspect_parents(pidfile.parent)
    finally:
        # Inventory failure must not leave known owned processes frozen indefinitely.
        descendants = _owned(parents, root)
        for pid in sorted(stopped - {root}, reverse=True):
            if pid in descendants:
                _signal(pid, signal.SIGKILL)
        _signal(root, signal.SIGKILL)
        pidfile.unlink(missing_ok=True)
