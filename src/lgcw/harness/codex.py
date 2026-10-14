"""Official Codex SDK adapter with an isolated runtime and explicit role policies."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import IO
from uuid import UUID, uuid4

from codex_cli_bin import bundled_codex_path, bundled_path_dir
from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    AsyncThread,
    AsyncTurnHandle,
    CodexConfig,
    Input,
    Sandbox,
    SkillInput,
    TextInput,
)
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    ItemCompletedNotification,
    MessagePhase,
    ReasoningEffort,
    ThreadTokenUsage,
    ThreadTokenUsageUpdatedNotification,
    TurnCompletedNotification,
)
from openai_codex.models import JsonObject
from pydantic import BaseModel, ValidationError

from lgcw.harness.env import build_codex_env
from lgcw.harness.errors import HarnessError, HarnessOutputError, HarnessSessionLostError
from lgcw.harness.process import terminate_runtime
from lgcw.harness.prompts import fence
from lgcw.harness.records import TokenCounts, map_error, map_turn_error, read_counts, turn_usage
from lgcw.live import require_live
from lgcw.models.base import strict_json_schema
from lgcw.models.config import WorkflowConfig
from lgcw.models.harness import SessionRef, SessionSpec, TurnInput, TurnOutcome
from lgcw.runlog import redact


def rollout_path(codex_home: Path, session_id: str) -> Path | None:
    """Find exactly this session's own rollout, rejecting glob injection and symlink escapes."""
    try:
        if str(UUID(session_id)) != session_id:
            raise ValueError("noncanonical session id")
    except ValueError as exc:
        raise ValueError("invalid session id") from exc
    root = codex_home / "sessions"
    paths = sorted(root.glob(f"**/rollout-*{session_id}*.jsonl"))
    for path in paths:
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("rollout symlink escapes session folder")
    if len(paths) > 1:
        raise HarnessError("ambiguous session rollout")
    return paths[0] if paths else None


def _sandbox(role: str) -> Sandbox:
    return Sandbox.workspace_write if role == "builder" else Sandbox.read_only


def _policy(role: str) -> JsonObject:
    return {
        "sandbox_workspace_write.network_access": role == "builder",
        "analytics.enabled": False,
        "otel.metrics_exporter": "none",
    }


class CodexHarness:
    """Own one AsyncCodex server, with a process lock on the dedicated login directory."""

    def __init__(
        self,
        config: WorkflowConfig,
        *,
        allow_live: bool = False,
        worktree: Path | None = None,
        sdk_factory: Callable[[CodexConfig], AsyncCodex] = AsyncCodex,
        runtime_cleanup: Callable[[Path], Awaitable[None]] = terminate_runtime,
    ) -> None:
        require_live("CodexHarness", allow_live)
        if worktree is not None and not worktree.is_absolute():
            raise HarnessError("trusted worktree must be absolute")
        self._worktree = worktree.resolve() if worktree is not None else None
        self._logger = logging.getLogger(__name__)
        self._config = config
        self._terminate_runtime = runtime_cleanup
        env = build_codex_env(config, os.environ)
        # CodexConfig.env merges the parent. env -i replaces it at the actual Rust process.
        path_dir = bundled_path_dir()
        if path_dir is not None:
            env["PATH"] = str(path_dir) + os.pathsep + env["PATH"]
        self._runtime_pid = config.codex_home / f"lgcw-runtime-{uuid4()}.pid"
        script = 'umask 077; printf "%s" "$$" > "$1"; shift; exec /usr/bin/env -i "$@"'
        args = (
            "/usr/bin/env",
            "-i",
            *(f"{key}={value}" for key, value in env.items()),
            "/bin/sh",
            "-c",
            script,
            "lgcw-runtime",
            str(self._runtime_pid),
            *(f"{key}={value}" for key, value in env.items()),
            str(bundled_codex_path()),
            "-c",
            "analytics.enabled=false",
            "-c",
            'otel.metrics_exporter="none"',
            "app-server",
            "--listen",
            "stdio://",
        )
        self._codex = sdk_factory(CodexConfig(launch_args_override=args))
        self._started = False
        self._closed = False
        self._lock: IO[str] | None = None
        self._start_lock = asyncio.Lock()
        self._fresh: dict[str, AsyncThread] = {}
        self._specs: dict[str, SessionSpec] = {}
        self._trusted_cwds: dict[str, Path] = {}
        self._active: dict[str, AsyncTurnHandle | None] = {}

    def _cleanup_diagnostic(self, stage: str, error: Exception) -> None:
        self._logger.warning(
            "Codex cleanup %s (%s): %s", stage, type(error).__name__, redact(str(error))
        )

    async def _shutdown_runtime(self) -> None:
        failure: Exception | None = None
        try:
            await self._terminate_runtime(self._runtime_pid)
        except Exception as exc:
            failure = exc
            self._cleanup_diagnostic("process inventory", exc)
        finally:
            try:
                await self._codex.close()
            except Exception as exc:
                self._cleanup_diagnostic("SDK close", exc)
                if failure is None:
                    failure = exc
        if failure is not None:
            raise HarnessError("runtime cleanup failed: " + str(failure)) from None

    async def _ensure_started(self) -> None:
        async with self._start_lock:
            if self._closed:
                raise HarnessError("CodexHarness is closed")
            if self._started:
                return
            self._config.codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock = (self._config.codex_home / "lgcw-server.lock").open("a+")
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                lock.close()
                raise HarnessError("dedicated CODEX_HOME already has a workflow server") from exc
            self._lock = lock
            try:
                await self._codex.__aenter__()
                self._started = True
            except BaseException:
                try:
                    await self._shutdown_runtime()
                except Exception:
                    pass  # diagnostics are recorded; preserve the original startup/cancel cause
                finally:
                    lock.close()
                    self._lock = None
                raise

    async def start_session(self, spec: SessionSpec) -> SessionRef:
        """Start a fresh role with deny-all approvals and the trusted network/sandbox policy."""
        if spec.sandbox != _sandbox(spec.role).name or spec.network != (spec.role == "builder"):
            raise HarnessError("session spec disagrees with role sandbox/network policy")
        if not spec.cwd.is_absolute() or not spec.cwd.is_dir():
            raise HarnessError("session cwd must be an existing absolute worktree")
        if spec.role == "builder":
            if self._worktree is None:
                self._worktree = spec.cwd.resolve()
            self._check_worktree(spec.cwd, self._worktree)
        ReasoningEffort(spec.effort)
        try:
            await self._ensure_started()
            thread = await self._codex.thread_start(
                cwd=str(spec.cwd),
                model=spec.model,
                sandbox=_sandbox(spec.role),
                approval_mode=ApprovalMode.deny_all,
                config=_policy(spec.role),
            )
            self._fresh[thread.id] = thread
            self._specs[thread.id] = spec
            self._trusted_cwds[thread.id] = spec.cwd.resolve()
            return SessionRef(session_id=thread.id, role=spec.role)
        except Exception as exc:
            raise map_error(exc) from exc

    async def _thread(self, session: SessionRef) -> tuple[AsyncThread, SessionSpec]:
        await self._ensure_started()
        spec = self._specs.get(session.session_id)
        if spec is not None and session.role != spec.role:
            raise HarnessSessionLostError("session role does not match the started thread")
        fresh = self._fresh.get(session.session_id)
        if fresh is not None and spec is not None:
            return fresh, spec
        # Supply the immutable role policy on first resume in a new server. Cached resumes
        # keep their original policy; the spec above rejects role changes. A turn-level
        # workspace_write preset would reset builder network access to False.
        thread = await self._codex.thread_resume(
            session.session_id,
            sandbox=_sandbox(session.role),
            approval_mode=ApprovalMode.deny_all,
            config=_policy(session.role),
            cwd=str(spec.cwd) if spec else None,
            model=spec.model if spec else self._config.model,
        )
        saved = await thread.read(include_turns=True)
        if any(turn.status.value == "inProgress" for turn in saved.thread.turns):
            raise HarnessError("session has an unfinished turn; reconcile before dispatch")
        if spec is None:
            effort = (
                self._config.builder_effort
                if session.role == "builder"
                else (
                    self._config.verifier_effort
                    if session.role == "verifier"
                    else self._config.reviewer_effort["standard"]
                )
            )
            spec = SessionSpec(
                role=session.role,
                cwd=Path(saved.thread.cwd.root),
                sandbox=_sandbox(session.role).name,
                network=session.role == "builder",
                effort=effort,
                model=self._config.model,
            )
            self._specs[session.session_id] = spec
        return thread, spec

    def _check_worktree(self, cwd: Path, trusted: Path | None) -> None:
        if not cwd.is_absolute() or not cwd.is_dir() or trusted is None or cwd.resolve() != trusted:
            raise HarnessSessionLostError("session cwd differs from the trusted worktree")

    async def _collect(
        self, handle: AsyncTurnHandle, heartbeat: Callable[[], None]
    ) -> tuple[str, ThreadTokenUsage]:
        final: str | None = None
        fallback: str | None = None
        usage: ThreadTokenUsage | None = None
        completed: TurnCompletedNotification | None = None
        async for event in handle.stream():
            heartbeat()
            payload = event.payload
            if isinstance(payload, ItemCompletedNotification) and payload.turn_id == handle.id:
                item = payload.item.root
                if isinstance(item, AgentMessageThreadItem):
                    if item.phase == MessagePhase.final_answer:
                        final = item.text
                    elif item.phase is None:
                        fallback = item.text
            elif isinstance(payload, ThreadTokenUsageUpdatedNotification):
                if payload.turn_id == handle.id:
                    usage = payload.token_usage
            elif isinstance(payload, TurnCompletedNotification) and payload.turn.id == handle.id:
                completed = payload
        if completed is None:
            raise HarnessError("turn completion receipt missing")
        if completed.turn.status.value != "completed":
            error = completed.turn.error
            if error is not None:
                raise map_turn_error(error)
            raise HarnessError(f"turn ended with status {completed.turn.status.value}")
        if usage is None:
            raise HarnessError("completed turn has no measured usage")
        text = final if final is not None else fallback
        if text is None:
            raise HarnessOutputError("completed turn has no final structured response")
        return text, usage

    async def run_turn[M: BaseModel](
        self,
        session: SessionRef,
        turn: TurnInput,
        output: type[M],
        *,
        heartbeat: Callable[[], None],
    ) -> TurnOutcome[M]:
        """Run one schema-validated turn, allowing one output correction and interrupting cancel."""
        schema = strict_json_schema(output)
        rollout_path(self._config.codex_home, session.session_id)  # validate before service I/O
        if session.session_id in self._active:
            raise HarnessError("session already has an active turn")
        self._active[session.session_id] = None
        started = time.monotonic()
        handle: AsyncTurnHandle | None = None
        thread: AsyncThread | None = None
        dispatch: asyncio.Task[AsyncTurnHandle] | None = None
        try:
            baseline = rollout_path(self._config.codex_home, session.session_id)
            fresh = session.session_id in self._fresh
            before = read_counts(baseline)
            text = turn.text
            if turn.data is not None:
                text += "\n\n" + fence(turn.data, turn.data_label or "external-data")
            for attempt in range(2):
                handle = None
                dispatch = None
                self._active[session.session_id] = None
                thread, spec = await self._thread(session)
                if baseline is None and not fresh:
                    raise HarnessSessionLostError(
                        "resumed session has no durable token accounting baseline"
                    )
                trusted = self._trusted_cwds.get(session.session_id)
                if trusted is None and session.role == "builder":
                    trusted = self._worktree
                self._check_worktree(spec.cwd, trusted)
                inputs: Input = [
                    SkillInput(name=Path(turn.skill).parent.name, path=turn.skill),
                    TextInput(
                        text=text
                        if attempt == 0
                        else text
                        + "\n\nYour previous answer did not match the required output schema. "
                        "Return a valid JSON answer matching that schema."
                    ),
                ]
                # Fresh start/resume above explicitly sets the role policy for THIS turn.
                # Omit the preset here to preserve builder network=True (see D-034).
                handle = None
                dispatch = asyncio.create_task(
                    thread.turn(
                        inputs,
                        approval_mode=ApprovalMode.deny_all,
                        cwd=str(spec.cwd),
                        effort=ReasoningEffort(spec.effort),
                        model=spec.model,
                        output_schema=schema,
                    )
                )
                handle = await asyncio.shield(dispatch)
                self._fresh.pop(session.session_id, None)
                self._active[session.session_id] = handle
                try:
                    answer, tokens = await self._collect(handle, heartbeat)
                    result = output.model_validate_json(answer)
                except (HarnessOutputError, ValidationError) as exc:
                    if attempt == 0:
                        continue
                    raise HarnessOutputError("agent output failed schema validation twice") from exc
                total = tokens.total
                after = TokenCounts(
                    input_tokens=total.input_tokens,
                    cached_input_tokens=total.cached_input_tokens,
                    output_tokens=total.output_tokens,
                    reasoning_output_tokens=total.reasoning_output_tokens,
                )
                return TurnOutcome(
                    session_id=session.session_id,
                    output=result,
                    usage=turn_usage(
                        before,
                        after,
                        context_window=tokens.model_context_window,
                        context_input_tokens=tokens.last.input_tokens,
                    ),
                    duration_s=time.monotonic() - started,
                    rollout_path=rollout_path(self._config.codex_home, session.session_id),
                )
            raise HarnessOutputError("agent output missing")
        except asyncio.CancelledError:
            try:
                # turn/start may have dispatched before its RPC reply reaches us. Preserve
                # that reply so cancellation still obtains and interrupts the paid handle.
                if handle is None and dispatch is not None:
                    handle = await asyncio.wait_for(asyncio.shield(dispatch), timeout=10)
                if handle is not None:
                    await asyncio.shield(asyncio.wait_for(handle.interrupt(), timeout=1.0))
                    if thread is not None:
                        async with asyncio.timeout(1):
                            while True:
                                history = await thread.read(include_turns=True)
                                if any(
                                    item.id == handle.id and item.status.value != "inProgress"
                                    for item in history.thread.turns
                                ):
                                    break
                                await asyncio.sleep(0.01)
            except Exception as exc:
                self._cleanup_diagnostic("cancel interrupt", exc)
                if dispatch is not None:
                    dispatch.cancel()
                    await asyncio.gather(dispatch, return_exceptions=True)
            finally:
                # Close reachable runtime work. Later code checks content because already
                # reparented children can escape this bounded inventory (D-034 R2).
                if handle is not None or dispatch is not None:
                    try:
                        await asyncio.shield(self.close())
                    except Exception:
                        pass  # logged by shutdown; CancelledError remains the control signal
            raise
        except Exception as exc:
            raise map_error(exc) from exc
        finally:
            self._active.pop(session.session_id, None)

    async def close(self) -> None:
        """Interrupt owned active turns, close the server and release the login lock."""
        async with self._start_lock:
            self._closed = True
            try:
                for handle in tuple(self._active.values()):
                    if handle is not None:
                        try:
                            await asyncio.wait_for(handle.interrupt(), timeout=1.0)
                        except Exception as exc:
                            self._cleanup_diagnostic("close interrupt", exc)
            finally:
                try:
                    await self._shutdown_runtime()
                finally:
                    if self._lock is not None:
                        self._lock.close()
                        self._lock = None
                    self._started = False
