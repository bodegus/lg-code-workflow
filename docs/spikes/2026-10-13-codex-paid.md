# T10 pinned SDK agent-turn qualification

Question: can SDK 0.162.1 combine SkillInput + TextInput, use a strict output schema after
server restart, measure usage, locate its rollout, enforce agent write policies and interrupt
an active command? Expected yes; a thread without its first turn is expected to be unresumable.

Owner authorization: PR #2 comment 6152173120. Four tiny turns in a temporary git checkout under
~/.lgcw/spikes, using the owner-created dedicated ~/.lgcw/codex login. The task's “fresh CODEX_HOME”
is interpreted as the workflow's dedicated login rather than copying credentials to a temporary
home. No authentication file contents were read or copied. All temporary workspaces were removed.
The ignored probe is throwaway; this is its retained transcript, not a probe distribution.

Calls: AsyncCodex(CodexConfig(launch_args_override=env-clearing argv)); thread_start(cwd,
sandbox=workspace_write, approval_mode=deny_all, config={sandbox_workspace_write.network_access:
true}); thread.run([SkillInput(exact path), TextInput], output_schema=strict_json_schema(Result),
approval_mode=deny_all, effort=low). Close the server, then thread_resume(id, sandbox,
approval_mode=deny_all, config=the same policy), followed by the same schema-bearing run.
Fresh read_only thread uses Sandbox.read_only on its turn. Cancel a stream-consumer task after
an actual command-start notification; its cancellation handler calls handle.interrupt(). Read
thread history until the turn's terminal status is interrupted. No escalation or automatic tool
retry was authorized. No GitHub writes, merges, or default-branch pushes occurred.

```text
$ uv run python spikes/2026-10-13-codex-paid/probe.py
{"output": "{\"answer\":\"Remembered needle=amber. First command exited 0 and wrote control.txt. Second command exited 1: operation not permitted for .git/config. Both attempted separately; no escalation or retry.\",\"ok\":true}", "session": "01a136dd-565b-7440-93b4-6acd056fc399", "status": "completed", "usage": {"last": {"cache_write_input_tokens": 0, "cached_input_tokens": 14464, "input_tokens": 14726, "output_tokens": 56, "reasoning_output_tokens": 0, "total_tokens": 14782}, "model_context_window": 475000, "total": {"cache_write_input_tokens": 0, "cached_input_tokens": 28800, "input_tokens": 43853, "output_tokens": 153, "reasoning_output_tokens": 0, "total_tokens": 44006}}}
{"agent_git_config_changed": false, "control_write": true}
{"rollout_exists": true, "session": "01a136dd-565b-7440-93b4-6acd056fc399"}
{"output": "{\"answer\":\"amber\",\"ok\":true}", "session": "01a136dd-565b-7440-93b4-6acd056fc399", "status": "completed", "usage": {"last": {"cache_write_input_tokens": 0, "cached_input_tokens": 14592, "input_tokens": 14797, "output_tokens": 19, "reasoning_output_tokens": 0, "total_tokens": 14816}, "model_context_window": 475000, "total": {"cache_write_input_tokens": 0, "cached_input_tokens": 43392, "input_tokens": 58650, "output_tokens": 172, "reasoning_output_tokens": 0, "total_tokens": 58822}}}
{"output": "{\"answer\":\"Attempted once. The shell denied the write: `zsh:1: operation not permitted: denied.txt` (exit code 1). No escalation or retry.\",\"ok\":true}", "session": "01a136dd-8f8a-77c0-87ac-32c869a227de", "status": "completed", "usage": {"last": {"cache_write_input_tokens": 0, "cached_input_tokens": 18048, "input_tokens": 18354, "output_tokens": 51, "reasoning_output_tokens": 0, "total_tokens": 18405}, "model_context_window": 475000, "total": {"cache_write_input_tokens": 0, "cached_input_tokens": 18048, "input_tokens": 36591, "output_tokens": 105, "reasoning_output_tokens": 0, "total_tokens": 36696}}}
{"agent_read_only_denied": true}
{"cancel_interrupt": true, "status": "interrupted"}
{"pre_turn_resume_lost": true, "error_class": "InvalidRequestError"}
paid probe completed: 4 turns; temp workspace removed
```

The builder wrote control.txt, but an actual agent-tool append to .git/config was denied and
the file was independently byte-compared unchanged. This qualifies the agent context; the earlier
bare command/exec RPC did permit .git writes and is not used by the harness. Read-only denied its
normal write. Resume remembered amber across a server restart. Both output schemas validated.
Session-only-before-first-turn recovery produced InvalidRequestError/no rollout found, mapped
by the adapter to HarnessSessionLostError. T14 must seed a fresh builder under its journal rules.

Usage.total is cumulative across model requests and turns, while usage.last is only the final
model request. First turn total input=43853 vs last=14726. Second cumulative input=58650, so its
billable input=14797; cached input=43392-28800=14592, output=172-153=19. The adapter subtracts
pre-turn totals from the own-session rollout and records last.input_tokens separately as context
occupancy. No token estimate is substituted. The rollout token_count events matched all those
SDK totals exactly. An unparseable baseline fails before dispatch rather than inventing zero.

A subsequent free public SDK thread_resume inspected the effective policy for the materialized
probe thread (zero model turns):

```text
$ uv run python /tmp/lgcw-t10-policy-resume.py
{"resumed_policy": "workspaceWrite", "network": true, "approval": "never", "model_turns": 0}
```

The high-level SDK's turn-level Sandbox.workspace_write preset resets network_access=false.
The adapter explicitly sets the complete role policy at thread_start for a fresh first turn or
at thread_resume immediately before every later turn, then sends deny_all on turn itself and
omits that resetting preset. It never relies on an old process's policy.

Named product-adapter smoke (four turns; separate from the four-turn spike):

```text
$ LGCW_LIVE=1 uv run pytest tests/live/test_codex_smoke.py -m live -s
tests/live/test_codex_smoke.py first usage={'input_tokens': 14664, 'cached_input_tokens': 0, 'output_tokens': 20, 'reasoning_output_tokens': 0, 'context_window': 475000, 'context_input_tokens': 14664} duration_s=4.219
resumed usage={'input_tokens': 16307, 'cached_input_tokens': 0, 'output_tokens': 20, 'reasoning_output_tokens': 0, 'context_window': 475000, 'context_input_tokens': 16307} duration_s=3.647
cross_server_resume=True session=01a136e1-3a65-7a61-80c8-48409dac61e4 heartbeats=34
read_only_write_denied=True usage={'input_tokens': 36731, 'cached_input_tokens': 18176, 'output_tokens': 97, 'reasoning_output_tokens': 0, 'context_window': 475000, 'context_input_tokens': 18421}
active_command_cancelled=True dedicated_home_lock=True pre_turn_session_lost=True
======================= 1 passed, 255 warnings in 23.48s =======================
```

Verdict: all six spike questions confirmed, including process-restart resume. The named
adapter smoke also passed: strict first/resumed outputs, measured counters/rollout, heartbeat,
read-only denial, cancellation, a second server refused by the home lock, and pre-materialization
session loss. This proves the harness, not a complete workflow or merge-ready target PR. Failed
or interrupted turns still have unknown usage at the existing HarnessPort error boundary; their
own Codex rollout remains available for later inspection. No authentication/quota failure was
provoked live; deterministic fake-SDK tests prove their controller dispositions.

## Final adapter qualification and the failed intermediate run

An intermediate repeat failed after one turn: the random unused session ID contained digits
429, which the adapter incorrectly matched as HTTP 429. No quota exhaustion occurred. The
expected no-rollout error was misclassified. Deterministic 401/429-in-ID regressions failed,
then passed after status-code word-boundary matching; no assertion was weakened.

```text
$ LGCW_LIVE=1 uv run pytest tests/live/test_codex_smoke.py -m live -s
FAILED test_codex_smoke
HarnessQuotaError: JSON-RPC error -32600: no rollout found for thread id 01a136e5-cab6-72d2-8429-9627b08dbc90
```

After fixing that classification and adding the no-baseline/no-dispatch guard, the final named
adapter command passed unchanged. The complete spike/smoke work dispatched 17 tiny turns in total
(four in the spike, three passing four-turn adapter runs, one turn before the failing run).
Interrupted-turn usage is not estimated.

```text
$ LGCW_LIVE=1 uv run pytest tests/live/test_codex_smoke.py -m live -s
tests/live/test_codex_smoke.py first usage={'input_tokens': 14664, 'cached_input_tokens': 0, 'output_tokens': 20, 'reasoning_output_tokens': 0, 'context_window': 475000, 'context_input_tokens': 14664} duration_s=3.639
resumed usage={'input_tokens': 16307, 'cached_input_tokens': 0, 'output_tokens': 20, 'reasoning_output_tokens': 0, 'context_window': 475000, 'context_input_tokens': 16307} duration_s=3.800
cross_server_resume=True session=01a136e8-9210-7dc0-8910-082f981481f7 heartbeats=34
read_only_write_denied=True usage={'input_tokens': 36731, 'cached_input_tokens': 18176, 'output_tokens': 97, 'reasoning_output_tokens': 0, 'context_window': 475000, 'context_input_tokens': 18421}
active_command_cancelled=True dedicated_home_lock=True pre_turn_session_lost=True
======================= 1 passed, 255 warnings in 18.34s =======================
```

## Superseded qualification in review

The early immediate-absence cancellation checks above did not prove physical shell cleanup.
The strengthened R1 check observed delayed.txt after an interrupted turn. D-034 R1 and
2026-10-13-t10-review.md retain that failure, the owned-process cleanup correction and the
passing delayed-write/server-exit proof. The named live test also now proves actual read-only
execution by a same-call-ID tool receipt and loading AGENTS.md (max-bytes-zero was removed).
A cached thread ignores in-process policy changes; first resume on separate new servers applied
false then true in the free probe. Earlier text claiming arbitrary cached-policy reapplication
is superseded by that measured limit. Total T10 paid spike/smoke dispatches so far: 28.
