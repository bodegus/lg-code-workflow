# Pinned runtime contracts before T12

Questions before probing: does SDK env replace the parent (expected no from source), does an
env-clearing launcher isolate it (expected yes), does LangGraph inject NodeError/context and
route a handler Command (expected yes), does heartbeat-only idle timeout reach that handler
(expected yes), and can Pydantic accept an undecorated Protocol (expected no)?

Command: `uv run python spikes/2026-10-13-runtime-contracts/probe.py`.
Versions: langgraph 1.2.15, openai-codex 0.162.1. Temporary homes; no login or LLM turn.
The synthetic child records environment key names and presence of a synthetic inherited marker;
it never prints credential values or inherited environment values.

```text
direct {"keys": [], "synthetic_inherited": true}
isolated {"keys": ["CODEX_HOME", "HOME", "LANG", "PATH", "__CF_USER_TEXT_ENCODING"], "synthetic_inherited": false}
undecorated_protocol SchemaError
fatal {"text": "build:ValueError:context-ok"}
idle {"text": "build:NodeTimeoutError:context-ok"}
```

The four-key env setting alone is **refuted** as isolation. The env-clearing launcher removes the
synthetic inherited variable; Python's macOS runtime adds a CoreFoundation metadata key. This
does not yet prove the actual Codex app-server has exactly four keys.

Two actual-binary follow-up setup attempts failed, so that question remains **inconclusive**:

```text
TypeError: resolve_codex_bin() missing 1 required positional argument: 'ops'
TransportClosedError: Codex process closed stdout.
Error: CODEX_HOME points to "<temporary home>/codex", but that path does not exist
```

The first assumed a one-argument resolver; source inspection supplied the SDK's bundled runtime
helper for the second. The second omitted creation of the fresh home. Stop the actual-binary
follow-up here; preflight home existence before a future attempt. No auth/session/turn ran, and
no actual app-server environment qualification is claimed. A separate decorated-Protocol probe:

```text
decorated_protocol 1
```

LangGraph handler/context/idle behavior is **confirmed locally**. Pydantic ports need
runtime_checkable. Product graph tests must cover these contracts; T10 still requires all six
live turn checks after the dedicated owner login.

Registration type follow-up: the NodeFn Callable alias erases keyword parameter names, while
LangGraph's StateNode typing requires keyword runtime and does not include a required NodeError
parameter. A callable Protocol preserves runtime; an optional typed NodeError sentinel satisfies
registration and fails closed if injection is missing. Probe before applying:

```text
uv run mypy --strict spikes/2026-10-13-runtime-contracts/typing_probe.py
Success: no issues found in 1 source file
uv run python spikes/2026-10-13-runtime-contracts/typing_probe.py
{'text': 'bad:ValueError'}
```

No cast, type ignore or private LangGraph import is needed. Product tests exercise the handler.
Ruff rejected constructing the sentinel in an argument default. After recording the repeated
product B008 failure, the final probe moves the immutable sentinel to module scope:

```text
uv run ruff check spikes/2026-10-13-runtime-contracts/typing_probe.py
All checks passed!
uv run mypy --strict spikes/2026-10-13-runtime-contracts/typing_probe.py
Success: no issues found in 1 source file
uv run python spikes/2026-10-13-runtime-contracts/typing_probe.py
{'text': 'bad:ValueError'}
```
