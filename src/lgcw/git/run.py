"""Small async subprocess boundary with no inherited credentials or git redirection."""

from __future__ import annotations

import asyncio
import base64
import os
import signal
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import BinaryIO

from lgcw.models.base import Strict
from lgcw.runlog import redact


class GitResult(Strict):
    """Redacted subprocess result; authentication is never stored in argv."""

    argv: tuple[str, ...]
    code: int
    out: str
    err: str
    capture_truncated: bool = False


class CapturedStream(Strict):
    """A bounded capture with explicit completeness for machine-readable consumers."""

    text: str
    truncated: bool


def _environment(extra: Mapping[str, str] | None) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT")
        if key in os.environ
    }
    env.update(extra or {})
    env.update(
        {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    )
    return env


def _secrets(env: Mapping[str, str]) -> tuple[str, ...]:
    secrets: list[str] = []
    for key, value in env.items():
        if key.startswith("GIT_CONFIG_VALUE_") and value.upper().startswith(
            "AUTHORIZATION: BASIC "
        ):
            encoded = value.split()[-1]
            decoded = base64.b64decode(encoded, validate=True).decode()
            token = decoded.partition(":")[2]
            secrets.extend((value, encoded))
            if token:
                secrets.append(token)
    return tuple(secrets)


_CAPTURE_BYTES = 65536
_METADATA_STDOUT_BYTES = 1048576


def _capture(
    stream: BinaryIO, safe: Callable[[bytes], str], overlap: int, limit: int = _CAPTURE_BYTES
) -> CapturedStream:
    """Read a bounded snapshot and redact overlapping windows before clipping."""
    descriptor = stream.fileno()
    size = os.fstat(descriptor).st_size
    if size <= limit:
        encoded = safe(os.pread(descriptor, size, 0)).encode()
        if len(encoded) <= limit:
            return CapturedStream(text=encoded.decode(), truncated=False)
        marker_bytes = b"\n[... capture truncated after redaction ...]\n"
        head = (limit - len(marker_bytes)) // 2
        tail = limit - len(marker_bytes) - head
        return CapturedStream(
            text=(
                encoded[:head].decode(errors="ignore")
                + marker_bytes.decode()
                + encoded[-tail:].decode(errors="ignore")
            ),
            truncated=True,
        )
    marker = f"\n[... capture truncated; original stream {size} bytes ...]\n"
    head = (limit - len(marker.encode())) // 2
    tail = limit - len(marker.encode()) - head
    # Positional reads do not move a still-live escaped writer's shared file offset.
    # Overlap keeps a credential straddling either clip boundary whole for redaction.
    prefix_bytes = safe(os.pread(descriptor, head + 2 * overlap, 0)).encode()
    # Shrinking replacements can pull an incomplete outer-boundary credential into
    # the visible window. Discard the margin in redacted coordinates as well.
    prefix = prefix_bytes[: max(0, min(head, len(prefix_bytes) - overlap))].decode(errors="ignore")
    start = max(0, size - tail - 2 * overlap)
    suffix_bytes = safe(os.pread(descriptor, size - start, start)).encode()
    if start:
        suffix_bytes = suffix_bytes[overlap:]
    suffix = suffix_bytes[-tail:].decode(errors="ignore")
    return CapturedStream(text=prefix + marker + suffix, truncated=True)


async def run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 120,
    metadata_stdout: bool = False,
) -> GitResult:
    """Run bounded argv and stop its owned process group on every exit path.

    Metadata stdout opts into a fixed 1 MiB capture; stderr and ordinary logs stay at 64 KiB.
    Both modes redact before clipping and explicitly report incomplete capture.
    """
    environment = _environment(env)
    secrets = _secrets(environment)
    if any(redact(argument) != argument for argument in argv) or any(
        secret in argument for secret in secrets for argument in argv
    ):
        raise ValueError("credential is forbidden in subprocess argv")

    def safe(data: bytes) -> str:
        text = data.decode(errors="replace")
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        return redact(text)

    # Anonymous files avoid a child-held pipe keeping communicate() alive after the
    # parent exits or is killed. Captured bytes are redacted before any result/log escapes.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        except OSError as error:
            return GitResult(argv=argv, code=127, out="", err=safe(str(error).encode()))

        def kill() -> None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout_s)
        except TimeoutError:
            timed_out = True
            kill()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                pass  # capture/reaping is bounded even if the OS has not delivered exit
        except asyncio.CancelledError:
            kill()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                pass
            raise
        finally:
            # A successful gate must not leave descendants racing subsequent git checks.
            kill()
        overlap = max((len(secret.encode()) for secret in secrets), default=0) + 1024
        captured_out, captured_err = (
            _capture(
                stdout, safe, overlap, _METADATA_STDOUT_BYTES if metadata_stdout else _CAPTURE_BYTES
            ),
            _capture(stderr, safe, overlap),
        )
        return GitResult(
            argv=argv,
            code=124 if timed_out else process.returncode if process.returncode is not None else 1,
            out=captured_out.text,
            err=captured_err.text + ("\nprocess timed out" if timed_out else ""),
            capture_truncated=captured_out.truncated or captured_err.truncated,
        )


async def git(
    *args: str,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 120,
    metadata_stdout: bool = False,
) -> GitResult:
    """Run git with hooks/fsmonitor disabled, no prompts and a bounded lifetime."""
    return await run_process(
        ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args),
        cwd=cwd,
        env=env,
        timeout_s=timeout_s,
        metadata_stdout=metadata_stdout,
    )
