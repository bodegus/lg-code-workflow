"""Generic typed harness operations available only to agent graph nodes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from lgcw.models.harness import SessionRef, SessionSpec, TurnInput, TurnOutcome


class HarnessPort(Protocol):
    """Start explicit-role sessions, run typed turns and close the owned server."""

    async def start_session(self, spec: SessionSpec) -> SessionRef:
        """Create a fresh role-specific session in the requested sandbox."""
        ...

    async def run_turn[M: BaseModel](
        self,
        session: SessionRef,
        turn: TurnInput,
        output: type[M],
        *,
        heartbeat: Callable[[], None],
    ) -> TurnOutcome[M]:
        """Run a typed turn and refresh the node's idle heartbeat on progress."""
        ...

    async def close(self) -> None:
        """Close the harness's owned agent server."""
        ...
