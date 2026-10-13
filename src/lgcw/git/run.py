"""Small async subprocess boundary with no inherited credentials or git redirection."""

from __future__ import annotations

import asyncio
import base64
import os
import signal
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
    """Run an explicit argv, killing its process group on timeout or cancellation."""
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

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return GitResult(argv=argv, code=127, out="", err=safe(str(error).encode()))
    communication = asyncio.create_task(process.communicate())

    def kill() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        out, err = await asyncio.wait_for(asyncio.shield(communication), timeout_s)
    except TimeoutError:
        kill()
        out, err = await communication
        return GitResult(argv=argv, code=124, out=safe(out), err=safe(err) + "\nprocess timed out")
    except asyncio.CancelledError:
        kill()
        await communication
        raise
    return GitResult(
        argv=argv,
        code=process.returncode if process.returncode is not None else 1,
        out=safe(out),
        err=safe(err),
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
