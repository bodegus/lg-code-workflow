"""In-memory fake at the public official-SDK boundary; never starts a process."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from openai_codex import AsyncCodex, AsyncThread, AsyncTurnHandle, CodexConfig, RunInput
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    ItemCompletedNotification,
    ThreadItem,
    ThreadReadResponse,
    ThreadTokenUsage,
    ThreadTokenUsageUpdatedNotification,
    TokenUsageBreakdown,
    Turn,
    TurnCompletedNotification,
    TurnError,
    TurnInterruptResponse,
    TurnStatus,
)
from openai_codex.models import Notification


class FakeCodex(AsyncCodex):
    """Capture public SDK calls with scripted answers and optional blocked streaming."""

    def __init__(
        self, config: CodexConfig, answers: list[str | Exception], *, hang: bool = False
    ) -> None:
        super().__init__(config)
        self.config_seen = config
        self.answers = list(answers)
        self.hang = hang
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.dispatched = asyncio.Event()
        self.stream_started = asyncio.Event()
        self.reply_ready: asyncio.Event | None = None
        self.interrupted = False
        self.closed = False
        self.initialize_error: Exception | None = None
        self.close_error: Exception | None = None
        self.tokens = 0
        self.last_turn_id = ""
        self.in_progress = False
        self.interrupt_hangs = False
        self.interrupt_error: Exception | None = None
        self.interrupt_release = asyncio.Event()
        self.resume_started = asyncio.Event()
        self.resume_wait: asyncio.Event | None = None
        self.resume_error: Exception | None = None
        self.status = TurnStatus.completed
        self.turn_error: TurnError | None = None
        self.missing_usage = False
        self.cwd = Path.cwd()

    async def __aenter__(self) -> Self:
        self.calls.append(("initialize", {}))
        if self.initialize_error is not None:
            raise self.initialize_error
        return self

    async def close(self) -> None:
        self.closed = True
        self.interrupt_release.set()
        if self.close_error is not None:
            raise self.close_error

    async def thread_start(self, **kwargs: Any) -> AsyncThread:
        self.calls.append(("start", kwargs))
        self.cwd = Path(kwargs["cwd"])
        return FakeThread(self, str(uuid4()))

    async def thread_resume(self, thread_id: str, **kwargs: Any) -> AsyncThread:
        self.calls.append(("resume", kwargs | {"thread_id": thread_id}))
        self.resume_started.set()
        if self.resume_wait is not None:
            await self.resume_wait.wait()
        if self.resume_error is not None:
            raise self.resume_error
        return FakeThread(self, thread_id)


class FakeThread(AsyncThread):
    """Public SDK thread whose outputs come only from the script."""

    async def turn(self, input: RunInput, **kwargs: Any) -> AsyncTurnHandle:
        assert isinstance(self._codex, FakeCodex)
        sdk = self._codex
        sdk.calls.append(("turn", kwargs | {"input": input}))
        answer = sdk.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        sdk.tokens += 100
        sdk.dispatched.set()
        if sdk.reply_ready is not None:
            await sdk.reply_ready.wait()
        handle = FakeTurn(sdk, self.id, answer)
        sdk.last_turn_id = handle.id
        return handle

    async def read(self, *, include_turns: bool = False) -> ThreadReadResponse:
        assert isinstance(self._codex, FakeCodex)
        return ThreadReadResponse.model_validate(
            {
                "thread": {
                    "id": self.id,
                    "sessionId": self.id,
                    "cliVersion": "0.162.1",
                    "createdAt": 0,
                    "updatedAt": 0,
                    "cwd": str(self._codex.cwd),
                    "ephemeral": False,
                    "modelProvider": "openai",
                    "preview": "",
                    "source": "appServer",
                    "status": {"type": "idle"},
                    "turns": [{"id": "unfinished", "items": [], "status": "inProgress"}]
                    if self._codex.in_progress
                    else [{"id": self._codex.last_turn_id, "items": [], "status": "interrupted"}]
                    if self._codex.interrupted and self._codex.last_turn_id
                    else [],
                }
            }
        )


class FakeTurn(AsyncTurnHandle):
    """Stream typed public notification models, or wait for explicit interruption."""

    def __init__(self, sdk: FakeCodex, thread_id: str, answer: str) -> None:
        self._codex = sdk
        self.id = str(uuid4())
        self.thread_id = thread_id
        self.answer = answer

    async def stream(self) -> AsyncIterator[Notification]:
        assert isinstance(self._codex, FakeCodex)
        self._codex.stream_started.set()
        if self._codex.hang:
            await asyncio.Event().wait()
        counts = TokenUsageBreakdown(
            input_tokens=self._codex.tokens,
            cached_input_tokens=0,
            output_tokens=10,
            reasoning_output_tokens=0,
            total_tokens=self._codex.tokens + 10,
        )
        if not self._codex.missing_usage:
            yield Notification(
                "thread/tokenUsage/updated",
                ThreadTokenUsageUpdatedNotification(
                    thread_id=self.thread_id,
                    turn_id=self.id,
                    token_usage=ThreadTokenUsage(
                        last=counts, total=counts, model_context_window=1000
                    ),
                ),
            )
        yield Notification(
            "item/completed",
            ItemCompletedNotification(
                thread_id=self.thread_id,
                turn_id=self.id,
                completed_at_ms=0,
                item=ThreadItem(
                    root=AgentMessageThreadItem(
                        id="answer", text=self.answer, type="agentMessage", phase="final_answer"
                    )
                ),
            ),
        )
        yield Notification(
            "turn/completed",
            TurnCompletedNotification(
                thread_id=self.thread_id,
                turn=Turn(
                    id=self.id, items=[], status=self._codex.status, error=self._codex.turn_error
                ),
            ),
        )

    async def interrupt(self) -> TurnInterruptResponse:
        assert isinstance(self._codex, FakeCodex)
        self._codex.interrupted = True
        if self._codex.interrupt_error is not None:
            raise self._codex.interrupt_error
        if self._codex.interrupt_hangs:
            await self._codex.interrupt_release.wait()
        return TurnInterruptResponse()
