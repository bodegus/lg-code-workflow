"""Owned runtime cleanup includes descendants that start their own process groups."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lgcw.harness.process import terminate_runtime


@pytest.mark.unit
@pytest.mark.parametrize("query_fails", [False, True])
async def test_terminate_owned_runtime_and_detached_child(
    tmp_path: Path, query_fails: bool
) -> None:
    pidfile = tmp_path / "runtime.pid"
    childfile = tmp_path / "child.pid"
    delayed = tmp_path / "delayed"
    child = (
        "import os,time,pathlib; os.setsid(); "
        f"pathlib.Path({str(childfile)!r}).write_text(str(os.getpid())); "
        f"time.sleep(1); pathlib.Path({str(delayed)!r}).write_text('unexpected')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    pidfile.write_text(str(process.pid))
    try:
        async with asyncio.timeout(3):
            while not childfile.exists():
                await asyncio.sleep(0.01)
        if query_fails:
            queries = 0

            async def inspect_parents(cwd: Path) -> dict[int, int]:
                nonlocal queries
                queries += 1
                if queries > 1:
                    raise RuntimeError("process inventory failed during cleanup")
                return {process.pid: os.getpid(), int(childfile.read_text()): process.pid}

            with pytest.raises(RuntimeError, match="inventory failed"):
                await terminate_runtime(pidfile, inspect_parents=inspect_parents)
        else:
            await terminate_runtime(pidfile)
        process.wait(timeout=3)
        await asyncio.sleep(1.1)
        assert not delayed.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if childfile.exists():
            try:
                os.kill(int(childfile.read_text()), 9)
            except ProcessLookupError:
                pass


@pytest.mark.unit
async def test_terminate_runtime_refuses_self_or_foreign_parent(tmp_path: Path) -> None:
    pidfile = tmp_path / "runtime.pid"
    pidfile.write_text(str(os.getpid()))
    with pytest.raises(ValueError, match="owned"):
        await terminate_runtime(pidfile)
    # Use a controlled grandchild as the foreign-parent case, so a faulty guard cannot
    # signal the test runner's real parent during independent source-removal checks.
    foreign = tmp_path / "foreign.pid"
    script = (
        "import subprocess,sys,time,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)']); "
        f"pathlib.Path({str(foreign)!r}).write_text(str(child.pid)); time.sleep(10)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        async with asyncio.timeout(3):
            while not foreign.exists():
                await asyncio.sleep(0.01)
        pidfile.write_text(foreign.read_text())
        with pytest.raises(ValueError, match="owned"):
            await terminate_runtime(pidfile)
    finally:
        if foreign.exists():
            try:
                os.kill(int(foreign.read_text()), 9)
            except ProcessLookupError:
                pass
        parent.kill()
        parent.wait(timeout=3)
    await terminate_runtime(tmp_path / "absent.pid")
