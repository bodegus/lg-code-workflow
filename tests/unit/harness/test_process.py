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
        child_pid = int(childfile.read_text())
        async with asyncio.timeout(3):
            while True:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.02)
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


@pytest.mark.unit
async def test_process_failing_recheck_is_resumed_not_left_stopped(tmp_path: Path) -> None:
    pidfile, childfile = tmp_path / "runtime.pid", tmp_path / "child.pid"
    script = (
        "import subprocess,sys,time,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)']); "
        f"pathlib.Path({str(childfile)!r}).write_text(str(child.pid)); time.sleep(10)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    pidfile.write_text(str(parent.pid))
    try:
        async with asyncio.timeout(3):
            while not childfile.exists():
                await asyncio.sleep(0.01)
        child = int(childfile.read_text())
        queries = 0

        async def inventory(cwd: Path) -> dict[int, int]:
            nonlocal queries
            queries += 1
            return {parent.pid: os.getpid(), child: parent.pid if queries == 1 else 1}

        await terminate_runtime(pidfile, inspect_parents=inventory)
        parent.wait(timeout=3)
        async with asyncio.timeout(1):
            while True:
                state = subprocess.run(
                    ("/bin/ps", "-p", str(child), "-o", "state="),
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=1,
                ).stdout
                if "T" not in state:
                    break
                await asyncio.sleep(0.02)
    finally:
        if childfile.exists():
            try:
                os.kill(int(childfile.read_text()), 9)
            except ProcessLookupError:
                pass
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=3)
