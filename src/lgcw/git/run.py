"""Small async subprocess boundary with no inherited credentials or git redirection."""

from __future__ import annotations

import asyncio
import base64
import os
import signal
import tempfile
from collections.abc import Mapping
from pathlib import Path

from lgcw.models.base import Strict
from lgcw.runlog import redact


class GitResult(Strict):
    """Redacted subprocess result; authentication is never stored in argv."""

    argv: tuple[str, ...]
    code: int
    out: str
    err: str


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


async def run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 120,
) -> GitResult:
    """Run bounded argv and stop its owned process group on every exit path."""
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
        stdout.seek(0)
        stderr.seek(0)
        return GitResult(
            argv=argv,
            code=124 if timed_out else process.returncode if process.returncode is not None else 1,
            out=safe(stdout.read()),
            err=safe(stderr.read()) + ("\nprocess timed out" if timed_out else ""),
        )


async def git(
    *args: str, cwd: Path, env: Mapping[str, str] | None = None, timeout_s: float = 120
) -> GitResult:
    """Run git with hooks/fsmonitor disabled, no prompts and a bounded lifetime."""
    return await run_process(
        ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args),
        cwd=cwd,
        env=env,
        timeout_s=timeout_s,
    )
