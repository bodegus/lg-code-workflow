"""In-memory typed harness that cannot call an agent or network service."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ValidationError

from lgcw.harness.errors import HarnessError, HarnessOutputError, HarnessSessionLostError
from lgcw.harness.port import HarnessPort
from lgcw.models.harness import Role, SessionRef, SessionSpec, TurnInput, TurnOutcome, Usage


class FakeHarness(HarnessPort):
    """Script independent role outputs and retain every session and attempted turn."""

    def __init__(self, *, usage: Usage | None = None, session_prefix: str = "fake") -> None:
        self.usage = (
            usage
            if usage is not None
            else Usage(
                input_tokens=100,
                cached_input_tokens=20,
                output_tokens=10,
                reasoning_output_tokens=5,
                context_window=128000,
            )
        )
        self.usage_script: deque[Usage] = deque()
        self.session_prefix = session_prefix
        self.duration_s = 0.1
        self.rollout_path: Path | None = None
        self.sessions: list[SessionSpec] = []
        self.turns: list[tuple[SessionRef, TurnInput]] = []
        self.closed = False
        self._refs: dict[str, SessionRef] = {}
        self._scripts: dict[Role, deque[BaseModel | Exception]] = {}

    def script(self, role: Role, outputs: list[BaseModel | Exception]) -> None:
        """Append outcomes to one role without sharing another role's script."""
        self._scripts.setdefault(role, deque()).extend(outputs)

    async def start_session(self, spec: SessionSpec) -> SessionRef:
        """Record and return a fresh role-specific session."""
        if self.closed:
            raise HarnessError("harness is closed")
        self.sessions.append(spec)
        ref = SessionRef(
            session_id=f"{self.session_prefix}-{spec.role}-{len(self.sessions)}", role=spec.role
        )
        self._refs[ref.session_id] = ref
        return ref

    async def run_turn[M: BaseModel](
        self,
        session: SessionRef,
        turn: TurnInput,
        output: type[M],
        *,
        heartbeat: Callable[[], None],
    ) -> TurnOutcome[M]:
        """Consume a scripted outcome, validate its schema and emit a progress heartbeat."""
        if self.closed:
            raise HarnessError("harness is closed")
        if self._refs.get(session.session_id) != session:
            raise HarnessSessionLostError("unknown or mismatched fake session")
        self.turns.append((session, turn))
        heartbeat()
        script = self._scripts.get(session.role)
        if not script:
            raise HarnessError("fake output script is exhausted")
        value = script.popleft()
        if isinstance(value, Exception):
            raise value
        try:
            validated = output.model_validate(value.model_dump())
        except ValidationError:
            raise HarnessOutputError("scripted output does not match requested schema") from None
        return TurnOutcome[M](
            session_id=session.session_id,
            output=validated,
            usage=self.usage_script.popleft() if self.usage_script else self.usage,
            duration_s=self.duration_s,
            rollout_path=self.rollout_path,
        )

    async def close(self) -> None:
        """Close this fake; subsequent session or turn calls fail explicitly."""
        self.closed = True
