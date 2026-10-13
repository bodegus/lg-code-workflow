# 06 — What OpenClaw itself offers at v2026.9.9 (baseline and future host)

Status: COMPLETE (2026-10-13). Written progressively.
Research date: 2026-10-13. Pinned release under study: `openclaw/openclaw` tag `v2026.9.9`.

Legend: **verified** = checked against docs.openclaw.ai, the GitHub release notes, or source at the
`v2026.9.9` tag (link given). **inferred** = my reading/extrapolation, not directly confirmed.

## Contents
1. Native workflow engine (Lobster, TaskFlow, standing orders)
2. Cron / automation command jobs
3. HTTP hooks and gateway RPC (`agent`, `agent.wait`, `sessions.*`)
4. ACP / external agent harness support
5. OpenAI-compatible HTTP endpoints
6. Codex provider and harness (ChatGPT OAuth)
7. Synthesis: baseline vs LangGraph for S1–S10; hosting/supervising an external LangGraph run
8. Open questions

Tag facts (**verified**): `v2026.9.9` is an annotated, signed tag → commit
`bcfc88812a35243893585dbeca87ca41b48272ca`, published 2026-10-08
([release](https://github.com/openclaw/openclaw/releases/tag/v2026.9.9)). Permalinks below use
`https://github.com/openclaw/openclaw/blob/v2026.9.9/<path>` (tag-pinned).

---

## 1. Native workflow engine (Lobster, TaskFlow, standing orders)

### 1a. TaskFlow / Tasks ledger — removed (first absent in v2026.9.7; still absent at v2026.9.9)

- **verified** — The Tasks registry, the TaskFlow orchestration API and the bundled TaskFlow Webhooks
  plugin are gone at the tag. The automation overview says so directly: "The shared Tasks ledger,
  TaskFlow orchestration API, and TaskFlow Webhooks plugin have been removed"
  ([docs/automation/index.md L79-82](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/index.md#L79-L82)).
- **verified** — Removed SDK surface: `api.runtime.tasks`, `registerDetachedTaskRuntime`, the
  `agent-harness-task-runtime` subpath; "No compatibility facade remains". Replacements named:
  "native subagent launch/wait/history APIs, cron run history, and the ordinary Lobster runner".
  DB tables (`task_runs`, `task_delivery_state`, `flow_runs`) are left in place; cron only uses its
  `runtime='cron'` rows
  ([docs/plugins/sdk-migration/removed-surfaces.md, "Tasks and TaskFlow APIs removed"](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/sdk-migration/removed-surfaces.md)).
- **verified** — Webhooks plugin retirement and Doctor cleanup: "TaskFlow record actions from the
  retired plugin have no equivalent HTTP endpoint"; generic Gateway HTTP hooks remain
  ([docs/gateway/doctor/config-migrations.md "Retired TaskFlow Webhooks plugin"](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/doctor/config-migrations.md#retired-taskflow-webhooks-plugin)).
- **verified** — The removal PRs and the release that first shipped them:
  - [#158225 "refactor: retire the TaskFlow Webhooks plugin"](https://github.com/openclaw/openclaw/pull/158225), merged 2026-09-26 (merge `91b8f103`).
  - [#159179 "refactor: remove Tasks and TaskFlow runtime"](https://github.com/openclaw/openclaw/pull/159179), merged 2026-09-27 (merge `6652f7ea`); body: "The Tasks/TaskFlow APIs, CLI and SDK surfaces, and Chat/native Tasks panels retire immediately … intentionally provides no compatibility facade."
  - GitHub compare API: both merge commits are ancestors of `v2026.9.7`, `v2026.9.8`, `v2026.9.9`, and **not** of `v2026.9.6` → first shipped in **v2026.9.7** (published 2026-09-30).
- **verified (with a caveat)** — The *release note* for this is thin: `CHANGELOG/2026.9.7.md` has no
  prose bullet naming TaskFlow; the PRs appear only in its "Complete contribution record"
  (`- **PR #158225**`, `- **PR #159179**`, plus prerequisite batches #158221, #158217, #158222,
  #158702, #158776) ([CHANGELOG/2026.9.7.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/CHANGELOG/2026.9.7.md)).
  The user-facing statement of removal lives in the docs pages above, not the highlights.
- Implication: anything in our deploy that still references Tasks/TaskFlow (CLI, tools, Tasks panel)
  is dead at our pin (**inferred**).

### 1b. Lobster — ships as an official, separately installed, optional plugin

- **verified** — Source is in-tree at `extensions/lobster` (package `@openclaw/lobster@2026.9.9`,
  depends on runtime `@clawdbot/lobster@2026.9.13`, `minHostVersion >=2026.4.25`, category
  `agent-orchestration`) ([package.json](https://github.com/openclaw/openclaw/blob/v2026.9.9/extensions/lobster/package.json),
  [openclaw.plugin.json](https://github.com/openclaw/openclaw/blob/v2026.9.9/extensions/lobster/openclaw.plugin.json)).
- **verified** — Not installed or enabled by default: "Lobster is an **optional** plugin tool, not
  installed or enabled by default" → `openclaw plugins install @openclaw/lobster`, then
  `tools.alsoAllow: ["lobster"]` ([docs/tools/lobster.md L75-120](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/lobster.md#L75-L120)).
- **verified** — What it is: an *agent tool* (`lobster`) with two actions, `run` and `resume`
  ([lobster-tool.ts L21-36](https://github.com/openclaw/openclaw/blob/v2026.9.9/extensions/lobster/src/lobster-tool.ts#L21-L36)).
  It runs a pipeline string or a `.lobster`/YAML/JSON workflow file (`steps`, `args`, `env`,
  `condition`, `approval`) **in-process inside the Gateway**, with default `timeoutMs` 20 000 and
  `maxStdoutBytes` 512 000 ([lobster-tool.ts L46-48](https://github.com/openclaw/openclaw/blob/v2026.9.9/extensions/lobster/src/lobster-tool.ts#L46-L48)).
  Statuses: `ok | needs_approval | cancelled`; `needs_input` is rejected ("not supported by the
  OpenClaw Lobster tool yet") ([lobster-runner.ts L124-126](https://github.com/openclaw/openclaw/blob/v2026.9.9/extensions/lobster/src/lobster-runner.ts#L124-L126)).
  Disabled entirely in sandboxed tool contexts ([index.ts](https://github.com/openclaw/openclaw/blob/v2026.9.9/extensions/lobster/index.ts)).
  Approval resume state is small JSON under `~/.lobster/state` (`LOBSTER_STATE_DIR`)
  ([docs/tools/lobster.md L346-357](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/lobster.md#L346-L357)).
- **verified** — Known limitation: in the embedded runner, `openclaw.invoke` (calling back into
  OpenClaw tools such as `llm-task`) "is **not currently reliable**"
  ([docs/tools/lobster.md L186-233](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/lobster.md#L186-L233)).
- **verified** — The "managed Lobster approval flows" that could resume from a saved flow
  checkpoint were a TaskFlow feature (CHANGELOG 2026.9.5); after #159179 only "the ordinary Lobster
  runner" remains ([removed-surfaces.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/sdk-migration/removed-surfaces.md)).
- Assessment (**inferred**): Lobster is a *short, synchronous, in-Gateway shell pipeline invoked by an
  LLM as one tool call*. It is not a durable workflow engine: no crash-resume of a running pipeline
  (only approval checkpoints persist), each call is bounded by a tool-call timeout, no loops/back-edges
  in the DSL (steps + `condition` only), no LLM agent loops as steps (embedded `openclaw.invoke` is
  unreliable), and it runs with the Gateway's own process environment
  ([lobster-runner.ts L174](https://github.com/openclaw/openclaw/blob/v2026.9.9/extensions/lobster/src/lobster-runner.ts#L174) copies `process.env`),
  which conflicts with "agent loops hold no GitHub write credentials". It cannot express
  S3↔S4↔S5↔S6↔S7 bounded loops or a multi-hour CI wait. Useful at most for one deterministic leg
  (e.g. S5 publish) called by an agent — which re-introduces the LLM as the router.

### 1c. Standing orders — prose, not an engine

- **verified** — Standing orders are text in workspace bootstrap files (typically `AGENTS.md`),
  injected every session; "Combine with automations for time-based enforcement"
  ([docs/automation/standing-orders.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/standing-orders.md)).
  This is the same mechanism as our current brittle prose state machine; it gives no determinism.
- **verified** — The same page points at `openclaw agent exec` as "a strict, ephemeral CI or
  scripting entry point" that skips workspace bootstrap files (see §3).

### 1d. What replaced TaskFlow

- **verified** — Per the removal notes: native sub-agents (`sessions_spawn` + wait/history), cron
  ("Automations") run history, ACP harness sessions, and Lobster; "Each runtime owns execution and
  completion" ([docs/automation/index.md L73-82](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/index.md#L73-L82)).
  There is **no** native declarative, durable, multi-step graph engine at v2026.9.9.

---

## 2. Cron / "Automations" command jobs

Naming: at v2026.9.9 the scheduler is called **Automations**; `openclaw cron` is an alias of
`openclaw automations` (**verified**, [docs/automation/cron-jobs.md L12-14](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs.md#L12-L14)).
Gateway RPC names are still `cron.*` (`cron.add`, `cron.update`, `cron.run`, `cron.list`, `cron.history`).

### 2a. How a command payload runs (**verified**)

- Four payload kinds: system event, agent message, **command** (`--command <shell>` or
  `--command-argv <json>`, "A shell/process on the Gateway host, no model call"), script (headless
  code-mode JS using the agent's tools) ([payloads.md L14-23](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/payloads.md#L14-L23)).
- Command flags: `--command-cwd`, `--command-env KEY=VALUE`, `--command-input` (stdin),
  `--timeout-seconds` (default 10 min), `--no-output-timeout-seconds`, `--output-max-bytes`.
  Exit 0 → `ok`; non-zero, signal, timeout or no-output timeout → `error` and can trigger failure
  alerts. Printing only `NO_REPLY` suppresses delivery ([payloads.md L169-193](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/payloads.md#L169-L193)).
- Authority: "Command payloads are an operator-admin Gateway automation surface, not an agent
  `tools.exec` call" — create/update/run needs `operator.admin`; agent exec policy and approvals do
  **not** apply ([payloads.md L176](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/payloads.md#L176)).
  Conversational management can't create command payloads ("Create command payloads through the
  operator CLI or Gateway API", [managing-jobs.md L79](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/managing-jobs.md#L79)).
- Execution: `runCronCommandJob` → `runCommandWithTimeout(argv, {timeoutMs, cwd, input, env,
  noOutputTimeoutMs, maxOutputBytes, killProcessTree: true})`
  ([src/cron/command-runner.ts L93-141](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/cron/command-runner.ts#L93-L141)).
  `timeoutSeconds <= 0` means "effectively unbounded" (2^31-1 ms ≈ 24.8 days)
  ([L13-24](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/cron/command-runner.ts#L13-L24)), and
  the scheduler's own wall-clock watchdog is also disabled for a configured `<= 0`
  ([src/cron/service/timeout-policy.ts L19-31](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/cron/service/timeout-policy.ts#L19-L31)).
- **Environment inheritance**: the child gets the Gateway's `process.env` merged with `payload.env`
  ([src/process/exec-spawn.ts L391](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/process/exec-spawn.ts#L391),
  [L443-464](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/process/exec-spawn.ts#L443-L464)).
  So whatever secrets the Gateway process holds in env are visible to the command unless the argv
  wraps it (e.g. `["env","-i",…]`) (**inferred** mitigation).
- Concurrency: max **8** concurrent cron runs, hard-coded (`DEFAULT_CRON_MAX_CONCURRENT_RUNS = 8`,
  `resolveCronMaxConcurrentRuns()` returns it unconditionally)
  ([src/config/cron-limits.ts](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/config/cron-limits.ts)).
  A job with an active run is not runnable again (no self-overlap)
  ([src/cron/service/timer-runnable.ts L77-79](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/cron/service/timer-runnable.ts#L77-L79)).

### 2b. Timeouts, run history, retries, failure alerts (**verified**)

- Default budgets: command 10 min, script 5 min (cap 900 s), isolated agent turn 60-min scheduler
  watchdog (agent default `agents.defaults.timeoutSeconds` 48 h)
  ([how-it-works.md L20](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/how-it-works.md#L20),
  [payloads.md L209](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/payloads.md#L209)).
- Jobs and history persist in the shared SQLite state DB; schedules survive restarts
  ([how-it-works.md L16-18](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/how-it-works.md#L16-L18)).
  Interrupted runs are recorded as failures; a run whose live process cannot be verified becomes
  recoverable after >2 h ([how-it-works.md L38-48](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/how-it-works.md#L38-L48)).
- History: `openclaw automations runs <jobId> [--run-id]`; `status` (`ok|error|skipped`) vs
  `completionStatus` (`succeeded|failed|unknown`); kept 7 days / newest 2000 rows per job;
  `openclaw automations run <id> --wait --wait-timeout 10m` blocks and exits 0 only on
  `succeeded`; Gateway clients use `cron.history`
  ([managing-jobs.md L120-157, L226](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/managing-jobs.md#L120-L157)).
- Retry: one-shot transient errors retry, permanent errors disable; recurring jobs back off 30 s,
  60 s, 5 m, 15 m, 60 m ([managing-jobs.md L219-223](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/managing-jobs.md#L219-L223)).
- Failure alerts: default after 2 consecutive failures, 1 h cooldown, one alert per incident, one
  recovery notice; route via `failureAlert` → `delivery.failureDestination`/global
  `cron.failureAlert` → the job's announce target; webhook failure destinations carry the raw error.
  Unconditional backstop: a recurring job auto-disables after **10** consecutive execution
  failures (3 for schedule errors) and notifies the owner
  ([delivery.md L103-136](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/delivery.md#L103-L136)).
- Output: `--announce --channel … --to …`, `--webhook <url>` (bearer `cron.webhookToken`,
  strict SSRF policy unless `cron.webhookSsrfPolicy.allowedHostnames`), or none
  ([managing-jobs.md L167-210](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/managing-jobs.md#L167-L210)).

### 2c. Can it supervise a long-running external process?

- **inferred** — Technically yes, two ways, neither is a true process supervisor:
  1. *Long-lived command job* (`--timeout-seconds 0`, an `every 5m` schedule): the job runs the
     LangGraph process in the foreground; when it exits/crashes the run records `error`, the next
     slot (after back-off) restarts it. Costs one of only 8 cron slots for the whole lifetime;
     output is captured to a byte cap, not streamed; if the Gateway restarts, the child is
     killed/orphaned and the run is recorded as interrupted (child kill-on-restart behaviour
     not verified). Back-off reaches 60 min and auto-disable triggers at 10 consecutive errors.
  2. *Short "ensure-running / poll" command job* (recommended): every N minutes run an idempotent
     script such as `wf status --thread <id> || wf resume --thread <id> --detach` that exits
     quickly with 0 (healthy/progressing), prints `NO_REPLY` when nothing changed, prints a short
     status line when the PR became merge-ready or blocked (→ announce to the operator channel), and
     exits non-zero when stuck (→ failure alert after 2, auto-disable after 10). The LangGraph
     checkpointer gives crash-resume; cron gives the heartbeat, history, alerting and a human-visible
     audit trail. This keeps cron runs short and does not hold a slot.
- **inferred** — Prefer launchd (`KeepAlive`) / systemd (`Restart=on-failure`) for real
  restart-on-crash of a daemon, with cron as the *monitor/alerter*. The docs themselves recommend
  hard-kill escalation (`timeout -k`) when an external scheduler drives `openclaw agent`
  ([how-it-works.md L23](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/how-it-works.md#L23)).

---

## 3. HTTP hooks and Gateway RPC for starting/awaiting agent turns

### 3a. Gateway HTTP hooks: `POST /hooks/wake`, `POST /hooks/agent`, `POST /hooks/<mapping>` (**verified**)

- Disabled by default; enable with `hooks.enabled`, a **dedicated** `hooks.token`, `hooks.path`,
  `hooks.allowedAgentIds`; auth via `Authorization: Bearer` or `x-openclaw-token` (query token
  rejected); POST JSON only; body ≤ 256 KiB; 20 bad auths/60 s → 429
  ([docs/automation/cron-jobs/webhooks.md L21-39, L132-142](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/webhooks.md#L21-L39),
  [docs/gateway/config-hooks.md L59-80](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-hooks.md#L59-L80)).
- `/hooks/wake`: enqueue a short trusted system event into an agent's main session, optionally an
  immediate heartbeat; returns `{ok, mode, eventOutcome: queued|coalesced}` — not proof the heartbeat ran.
- `/hooks/agent`: submit an agent turn (`message`, `agentId`, `sessionKey`, `sessionMode`
  `isolated|persistent`, `model`, `thinking`, `timeoutSeconds`, `deliver`, `channel`/`to`,
  `idempotencyKey`, `waitForCompletion`) ([config-hooks.md L106-124](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-hooks.md#L106-L124)).
  Default returns `200 {ok, runId}` after *admission* (≤ 15 s, else 503 and the work is cancelled).
  With `waitForCompletion: true` the response stays open and returns
  `completion: {status: ok|error|skipped, replyDisposition: visible|silent|empty, delivered…}` —
  and "**The response never includes model output or summaries**"
  ([webhooks.md L69-106](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/webhooks.md#L69-L106),
  [config-hooks.md L223-235](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-hooks.md#L223-L235)).
- Idempotency: `Idempotency-Key` header (≤ 256 chars) replays the same run/completion; replay
  state is in memory and "Restart clears all replay state"
  ([config-hooks.md L211-222](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-hooks.md#L211-L222)).
- Content is "safety-wrapped" as external content; isolated hook turns get the "unattended run
  contract" (final reply must be the deliverable; no clarifying questions)
  ([payloads.md L269-273](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/payloads.md#L269-L273)).
- Fit (**inferred**): good as a *notification* path from an external LangGraph run into OpenClaw
  (e.g. `/hooks/wake` "PR #123 merge-ready" or "blocked: question X" to the operator's main
  session), and as a fire-and-forget way to start an OpenClaw agent turn. Poor as a builder/reviewer
  step invoker: it returns no reply text, the work product would have to be read back from the
  workspace/git or the session transcript via RPC, and replay state is lost on Gateway restart.

### 3b. Gateway RPC: `agent`, `agent.wait`, `sessions.*`, `chat.*` (**verified** unless marked)

- Transport: WebSocket + RPC; the documented integration path for "a script, dashboard, CI job …
  [to] start agent runs, stream events, wait for results, cancel work". "For agent runs, start with
  the `agent` RPC and pair it with `agent.wait` for a terminal result. For durable conversation
  state, use the `sessions.*` methods" ([docs/gateway/external-apps.md L13-61](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/external-apps.md#L13-L61)).
  Official clients are npm packages only (`@openclaw/gateway-client`, `@openclaw/gateway-protocol`,
  pinned at 2026.8.1 in the guide) — **no Python client**
  ([docs/gateway/clients.md L24](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/clients.md#L24)).
- `agent` params (closed schema): `message`, `agentId`, `provider`, `model`, `sessionKey`/`sessionId`,
  `thinking`, `timeout`, `cwd`, `promptMode` (`full|minimal|none`), `extraSystemPrompt`,
  `bootstrapContextMode`, `deliver`, `disableMessageTool`, `label`, required `idempotencyKey`, and
  (semantics not checked) `swarmCollector`/`swarmOutputSchema`
  ([packages/gateway-protocol/src/schema/agent.ts L289-358](https://github.com/openclaw/openclaw/blob/v2026.9.9/packages/gateway-protocol/src/schema/agent.ts#L289-L358)).
  It answers `{runId, acceptedAt}` immediately (an `accepted` frame) and, for clients that request
  `expectFinal`, a second final frame
  ([docs/concepts/agent-loop.md L20-24](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/concepts/agent-loop.md#L20-L24),
  [packages/gateway-client/src/pending-request.ts L224-227](https://github.com/openclaw/openclaw/blob/v2026.9.9/packages/gateway-client/src/pending-request.ts#L224-L227)).
- `agent.wait {runId, timeoutMs}` (default 30 s, wait-only, never cancels) → `{status:
  ok|error|timeout|pending, startedAt, endedAt, error?}`; `stopReason: "superseded"` when a newer
  writer replaced the run; `timeoutPhase: "gateway_draining"` on shutdown
  ([schema L379-383](https://github.com/openclaw/openclaw/blob/v2026.9.9/packages/gateway-protocol/src/schema/agent.ts#L379-L383),
  [agent-loop.md L189-201](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/concepts/agent-loop.md#L189-L201)).
  Reply text comes from the `agent` final frame or `chat.history`/`chat.message.get`, not from `agent.wait`.
- Agent run budget: `agents.defaults.timeoutSeconds` default **172 800 s (48 h)**; `0` = unlimited;
  model idle watchdog 120 s cloud / 300 s self-hosted ([agent-loop.md L199-206](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/concepts/agent-loop.md#L199-L206)).
- `sessions.*` highlights ([docs/gateway/protocol/rpc-session-control.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/protocol/rpc-session-control.md)):
  `sessions.create` (optionally `worktree: true` + `worktreeBaseRef`/`worktreeName` → a **managed git
  worktree** persisted on the session row; optional initial turn), `sessions.send`, `chat.send`
  (`queueMode` steer/followup/interrupt), `sessions.abort {key, runId}`, `sessions.list`
  (`hasActiveRun`, `activeRunIds`), `sessions.describe/get`, `chat.history` (cursor/delta catch-up),
  `sessions.messages.subscribe` (live transcript events), `sessions.patch` (model/thinking per
  session), and `sessions.github.options|publish|status|confirm` (a native GitHub publication flow
  for a session's workspace; its exact effects — push only vs PR — were **not verified** here).
- No-WebSocket options for a Python host (**verified**):
  - `openclaw gateway call <method> --params '<json>' --expect-final --json --timeout <ms>` — the
    CLI's low-level RPC helper; `--expect-final` is "mainly for agent-style RPCs"
    ([docs/cli/gateway/query.md L320-378](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/cli/gateway/query.md#L320-L378)).
  - Bundled, opt-in **Admin HTTP RPC** plugin: `POST /api/v1/admin/rpc` with Gateway auth; its
    allowlist includes `cron.*`, `config.*`, `agents.*`, `health`, `logs.tail`, `gateway.restart.request`,
    but **not** `agent`, `agent.wait`, `sessions.*` or `chat.*`
    ([docs/plugins/admin-http-rpc.md "Allowed methods"](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/admin-http-rpc.md#allowed-methods)).
- Restart behaviour: transcripts, cron store, subagent settlement and delivery queues persist in
  SQLite; interrupted main-session turns auto-resume; **cron sessions, subagent sessions and
  ACP-managed sessions are not auto-resumed** (their owners handle it); terminal PTYs die
  ([docs/gateway/restart-recovery.md L20-31, L906-919](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/restart-recovery.md#L20-L31)).

### 3c. `openclaw agent exec` — Gateway-less, one-shot agent turn (**verified**)

- "runs one embedded agent turn without connecting to a Gateway. It is the recommended headless
  entry point for CI and coding automation because it owns setup, cleanup, output projection, and
  process status" ([docs/cli/agent.md L26-36](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/cli/agent.md#L26-L36);
  registered at [src/cli/program/register.agent-turn.ts L106-132](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/cli/program/register.agent-turn.ts#L106-L132)).
- `--cwd` = workspace and tool cwd (filesystem tools restricted to it), no bootstrap files,
  sandbox off, `coding` tool profile, temp state dir deleted afterwards (or `--state-dir`), `--config`
  / `--isolated` for reproducible config, `--model` + repeatable `--fallback`, `--thinking`,
  `--timeout` (default 600 s; `0` disables), `--json` stable envelope
  (`ok,status,final,payloads,usage,costUsd,toolSummary,model,provider,sessionId`); exit codes
  **0 ok / 1 error / 2 timeout** ([docs/cli/agent.md L36-113, L302-318](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/cli/agent.md#L36-L113)).
- Credentials: uses stored credentials and the configured `agentRuntime` harness (so the Codex
  harness and its ChatGPT login apply); `--auth-env-only` restricts to env provider keys, and
  "Provider auth variables remain available to model authentication but are omitted from
  agent-launched host commands" ([docs/cli/agent.md L48-50](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/cli/agent.md#L48-L50)).
- Fit (**inferred**): this is the most direct way to use OpenClaw *as the S3/S7 agent-loop engine
  from a LangGraph node*: `subprocess.run(["openclaw","agent","exec","--cwd",wt,"--message-file",p,
  "--json","--timeout","3600"], env=scrubbed_env)` → parse `final`. It needs no Gateway, and the
  graph keeps all routing. Caveats: one turn per call (the builder must finish its loop inside one
  turn; the 48 h runtime budget allows that), no structured-output contract (parse a JSON block from
  `final` or have the agent write `result.json` in the worktree), and `--state-dir` exclusivity
  means no concurrent execs against a shared state dir. Not tested here.

### 3d. Addendum to §2 — native process supervision and no-LLM watchers inside Automations (**verified**)

These two schedule kinds matter more for "host/supervise LangGraph later" than plain command jobs:

- **`stream` schedule = supervised long-lived process.** "A stream schedule keeps an
  operator-authored argv command running under the Gateway and fires the job from its stdout and
  stderr lines … Disabling or removing the job stops the process; Gateway shutdown waits for
  process-tree teardown. Fast failures restart with the scheduler's built-in error backoff. Five
  consecutive runs shorter than 60 seconds leave the job in an error state and use the normal
  failure-alert path" ([docs/automation/cron-jobs/schedules.md L42-61](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/schedules.md#L42-L61)).
  Source confirms: `STABLE_RUN_MS = 60_000`, `MAX_CONSECUTIVE_FAILURES = 5`; **any** exit while the
  job is enabled (including exit code 0) triggers a restart — immediately if the run lasted ≥ 60 s,
  otherwise with error back-off ([src/gateway/cron-stream-job-owner.ts L21-22, L285-313, L469-497](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/gateway/cron-stream-job-owner.ts#L469-L497)).
  The child is spawned with the **full Gateway `process.env`** and no per-job env
  ([same file L387-398](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/gateway/cron-stream-job-owner.ts#L387-L398)).
  `--stream-mode match --stream-match '<regex>'` turns matching stdout lines into a payload
  (agent turn, system event, or script; **command payloads are rejected** for stream schedules);
  one payload in flight, batches coalesce, min 30 s between fires, failed payloads not retried
  ([schedules.md L57-61](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/schedules.md#L57-L61)).
- **`on-exit` schedule**: "Fire once when a watched command exits" — then the job disables itself
  ([schedules.md L16-32](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/schedules.md#L16-L32)).
- **Condition watchers** (`trigger.script` on `every`/`cron`/`stream`): a headless script (≤ 30 s,
  ≤ 5 tool calls, min interval 30 s, 16 KB persisted `state`) decides `fire: true|false`; only
  then does the payload run. The docs' own example polls `gh pr checks 123` and fires an agent turn
  on CI status change — i.e. an LLM-free CI poll natively. Caveat in the docs: trigger and script
  payloads "run unattended … with the owning agent's **full tool policy, including `exec`**"
  ([schedules.md L91-124](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/automation/cron-jobs/schedules.md#L91-L124)).

---

## 4. ACP / external agent harness support (Codex, Claude Code)

- **verified** — Three distinct ways OpenClaw runs an external coding agent
  ([docs/concepts/agent-runtimes.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/concepts/agent-runtimes.md),
  [docs/tools/acp-agents.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/acp-agents.md)):
  1. **Native Codex harness** (official `@openclaw/codex` plugin): an *embedded agent runtime*;
     `openai/*` model refs run through Codex app-server. This is the default path for Codex and
     the ChatGPT-subscription setup (see §6). "ACP is the external-harness path, not the default
     Codex path."
  2. **ACP via the official `@openclaw/acpx` plugin** (separately installed:
     `openclaw plugins install @openclaw/acpx`; `acp.enabled`, `acp.backend: "acpx"`,
     `acp.allowedAgents`) — harness ids include `claude` (Claude Code ACP adapter, "Requires
     Claude Code auth on the host"), `codex` (Codex ACP adapter, "Explicit ACP fallback only"),
     `gemini`, `opencode`, `cursor`, `copilot`, `droid`, `openclaw`, …
     ([docs/tools/acp-agents/quickstart.md L10-106](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/acp-agents/quickstart.md#L10-L106)).
     Started by an agent with `sessions_spawn({runtime:"acp", agentId, task, cwd, mode:"run"|"session",
     resumeSessionId, streamTo:"parent"})` or by an operator with `/acp spawn <id> --cwd … --mode
     oneshot|persistent` ([docs/tools/acp-agents/sessions.md L10-107](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/acp-agents/sessions.md#L10-L107)).
     Per-call timeouts are rejected; the budget is `agents.defaults.subagents.runTimeoutSeconds`.
     Permissions: acpx `permissionMode` default `approve-reads` and `nonInteractivePermissions:
     fail` — headless write/exec work needs `approve-all` (a "break-glass switch")
     ([docs/tools/acp-agents-setup.md L393-441](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/acp-agents-setup.md#L393-L441)).
     Codex ACP runs with an isolated `CODEX_HOME`; vendor auth must already exist on the host;
     other adapters may be fetched with `npx` on first use
     ([quickstart.md L43-51](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/acp-agents/quickstart.md#L43-L51)).
     ACP-managed sessions are not auto-resumed after a Gateway restart ("the connected IDE or
     client owns the resume", [restart-recovery.md L906-912](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/restart-recovery.md#L906-L912)).
  3. **CLI backends** (e.g. bundled `claude-cli`): "a text-only fallback" running a local CLI,
     with OpenClaw tools only via an optional loopback MCP bridge — "not a primary path"
     ([docs/gateway/cli-backends.md L10-16](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/cli-backends.md#L10-L16)).
- **verified** — Reverse direction: `openclaw acp` exposes a Gateway session *as* an ACP server for
  an IDE/client; `openclaw mcp serve` lets Codex/Claude Code connect as MCP clients to OpenClaw
  conversations ([acp-agents.md "Which page do I want?"](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/tools/acp-agents.md#which-page-do-i-want)).
- **inferred** — Baseline use: an OpenClaw agent can delegate S3/S7 to Claude Code or Codex via
  ACP, but routing between steps is still the parent LLM's job (the brittle conductor pattern),
  and delivery/resume of ACP children is owned by ACP, not by a deterministic graph. For the
  LangGraph prototype, calling a harness directly (Codex CLI/app-server, Claude Code) from a node
  is simpler than going through OpenClaw's ACP layer; ACP becomes interesting only if OpenClaw must
  show/steer those sessions in its UI.

---

## 5. OpenAI-compatible HTTP endpoints

- **verified** — Endpoints (all **disabled by default**, same port as the Gateway):
  `POST /v1/chat/completions`, `GET /v1/models`, `GET /v1/models/{id}`, `POST /v1/embeddings`
  (`gateway.http.endpoints.chatCompletions.enabled`), and `POST /v1/responses`
  (`gateway.http.endpoints.responses.enabled`)
  ([docs/gateway/openai-http-api.md L8-37](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/openai-http-api.md#L8-L37),
  [docs/gateway/openresponses-http-api.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/openresponses-http-api.md)).
- **verified** — What runs: **a full agent turn, not a raw model call**. "Requests run as a normal
  Gateway agent run (same codepath as `openclaw agent`)"; `model` is an *agent target*
  (`openclaw`, `openclaw/default`, `openclaw/<agentId>`); `x-openclaw-model` overrides the backend
  model; `x-openclaw-session-key` or `user` gives session continuity; `/v1/responses` supports
  `previous_response_id` (mapping survives restarts, 30 days) and `instructions` merged into the
  system prompt ([openai-http-api.md L21, L78-108](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/openai-http-api.md#L78-L108)).
  Source: the handler calls `runOpenAiCompatibleAgentCommand({message, extraSystemPrompt,
  clientTools, modelOverride, sessionKey, …})`
  ([src/gateway/openai-http.ts L730-752](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/gateway/openai-http.ts#L730-L752)).
- **verified** — Client function tools are supported (`tools`, `tool_choice` auto/none/required/
  pinned; tool calls are returned to the caller as `tool_calls` / `function_call` items; follow-up
  with `role:"tool"` / `function_call_output`), plus SSE streaming. Disconnecting cancels the run.
  ChatGPT-backed Codex Responses ignores `temperature`/`top_p` ([openai-http-api.md "Chat tool contract", "Streaming"](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/openai-http-api.md#chat-tool-contract)).
- **verified** — Auth: Gateway auth (`Authorization: Bearer <gateway token|password>`, or
  trusted-proxy). "Treat this endpoint as **full operator access**" — a bearer caller gets the full
  operator scope set incl. `operator.admin`, and turns count as owner-sender turns
  ([openai-http-api.md L39-70](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/openai-http-api.md#L39-L70)).
  2026.9.7 also "enforce[s] required sandboxing for new `/v1/chat/completions` and `/v1/responses`
  sessions" ([CHANGELOG/2026.9.7.md L168](https://github.com/openclaw/openclaw/blob/v2026.9.9/CHANGELOG/2026.9.7.md#L168)).
- **inferred** — Uses for the prototype:
  - As a model endpoint for LangGraph (`ChatOpenAI(base_url=".../v1", model="openclaw/<agent>")`)
    it would *technically* let LangGraph reach the ChatGPT/Codex subscription through OpenClaw's
    login, but every call is an OpenClaw agent turn with OpenClaw's system prompt, tools and
    session semantics layered on top — not a clean model API — and the credential is a full
    operator token. Poor fit for LangGraph's own tool loop.
  - As an *agent step* endpoint (send the task to `openclaw/builder`, read the final message) it
    works and returns the reply text (unlike `/hooks/agent`), but it is a long-held HTTP request
    for a multi-hour turn; `openclaw agent exec` or WS `agent` + `agent.wait` are better for that.

---

## 6. Codex provider and harness (ChatGPT OAuth)

- **verified** — Auth options for OpenAI in OpenClaw: **Codex login** (browser OAuth or device
  code; endpoint `https://chatgpt.com/backend-api/codex/responses`; OpenClaw refreshes its own
  profile), **Sign in with ChatGPT (Beta)** "SIWC" (authorize OpenClaw *as an app* to use your
  Codex allowance; endpoint `https://api.openai.com/v1/responses`; new in 2026.9.7), or an API key.
  CLI: `openclaw models auth login --provider openai --method oauth|device-code|siwc|api-key
  [--agent <id>] [--profile-id <id>]`. "Codex owns a separate native user-home login and its
  refresh" ([docs/providers/openai/authentication.md L11-171](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/providers/openai/authentication.md#L11-L171)).
- **verified** — Runtime vs auth are separate: OpenClaw's own runtime can use Codex login without
  the native harness; selecting `openai/<model>` with the `codex` plugin enabled runs the turn
  through Codex app-server ([authentication.md L94-111](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/providers/openai/authentication.md#L94-L111),
  [agent-runtimes.md "Codex surfaces"](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/concepts/agent-runtimes.md#codex-surfaces)).
- **verified** — How the harness runs Codex: the official `@openclaw/codex` plugin ships and
  manages `@openai/codex` **0.160.0** (bumped in v2026.9.9 for GPT-6.1 Sol) and launches
  `codex app-server --listen stdio://` from the plugin's own package, not from `PATH`; custom,
  remote, or desktop app-servers must be ≥ 0.149.0
  ([docs/plugins/codex-harness.md L536-552](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/codex-harness.md#L536-L552),
  [codex-harness-reference/app-server-transport.md L13-30](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/codex-harness-reference/app-server-transport.md#L13-L30),
  [CHANGELOG/2026.9.9.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/CHANGELOG/2026.9.9.md)).
  Codex owns the low-level loop (thread resume, native tools, compaction); OpenClaw owns channels,
  session files, model selection, OpenClaw dynamic tools, approvals and the transcript mirror
  ([codex-harness.md L10-16](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/codex-harness.md#L10-L16)).
- **verified** — How it authenticates with the ChatGPT login (the interesting design pattern):
  per-agent `CODEX_HOME` under OpenClaw state; the subscription profile is handed to Codex as
  `account/login/start` of type `chatgptAuthTokens` (in-memory, nothing written to
  `auth.json`); refresh is **inverted** — on 401 Codex sends `account/chatgptAuthTokens/refresh`
  back to OpenClaw, which refreshes from its own SQLite store, so "the refresh token stays in
  SQLite"; for subscription auth it strips `CODEX_API_KEY`/`OPENAI_API_KEY` from the child env;
  `appServer.clearEnv` can strip more; `appServer.homeScope: "user"` instead shares `~/.codex`
  with Codex CLI/Desktop ([codex-harness-reference/auth.md L13-160](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/codex-harness-reference/auth.md#L13-L160)).
  Both protocol pieces exist in Codex itself at `rust-v0.160.0`: `LoginAccountParams` has
  `type: "chatgptAuthTokens"` (`accessToken`, `chatgptAccountId`, `chatgptPlanType`) and the server
  request `account/chatgptAuthTokens/refresh`
  ([LoginAccountParams.ts @ rust-v0.160.0](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server-protocol/schema/typescript/v2/LoginAccountParams.ts),
  [ServerRequest.ts @ rust-v0.160.0](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server-protocol/schema/typescript/ServerRequest.ts)).
- **verified — secret-isolation caveat**: "OpenClaw does not rewrite `HOME` for normal local
  app-server launches. Codex-run subprocesses such as `openclaw`, `gh`, `git`, cloud CLIs, and
  shell commands see the normal process home and can find user-home config and tokens"
  ([auth.md L109-115](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/codex-harness-reference/auth.md#L109-L115)).
  So a Codex-harness builder on the Gateway host can use the operator's `gh` login unless the host
  is arranged otherwise — directly at odds with "agent loops hold no GitHub write credentials".
- **inferred** — For the LangGraph prototype: OpenClaw's SIWC/Codex-login profiles belong to
  OpenClaw's OAuth client; a Python workflow should not try to reuse OpenClaw's stored tokens. The
  clean options are (a) run Codex (CLI `codex exec` or `codex app-server`) under its *own* login in
  a dedicated `CODEX_HOME` (the "second, separate login"), copying OpenClaw's pattern of an isolated
  `CODEX_HOME`, scrubbed env and a different `HOME` for the sandbox; or (b) shell out to
  `openclaw agent exec`, which reuses OpenClaw's profile and harness without the workflow ever
  touching the tokens.

### 6b. Related native pieces found on the way (**verified**)

- **`github_publish` agent tool → `sessions.github.publish` RPC**: "Publish the current session's
  repository changes as a draft pull request … The Gateway publishes the accepted workspace,
  creates or reuses the draft pull request, and posts the result into the session transcript
  without resuming the agent … Publication credentials stay on the Gateway"
  ([src/agents/tools/github-publish-tool.ts L21-23](https://github.com/openclaw/openclaw/blob/v2026.9.9/src/agents/tools/github-publish-tool.ts#L21-L23)).
  This is a native analogue of S5 (deterministic, credential-holding publish), but it is triggered
  by an LLM tool call or a WS RPC, not by a graph.
- **GitHub identity for agent tools**: "When `tools.github` is omitted, local agent tools, the
  Codex harness, and Agent Settings follow normal `gh` resolution: `GH_TOKEN` or `GITHUB_TOKEN`
  from the Gateway process takes precedence, followed by the runtime user's `gh` keyring/config."
  `tools.github` can instead hand agents a managed `gh` identity (OAuth device flow with `repo`,
  `workflow` scopes, auto-refreshed) with per-agent overrides
  ([docs/gateway/config-tools/github-identity.md L12-40](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-tools/github-identity.md#L12-L40)).
  → By default OpenClaw agents *do* get whatever GitHub credentials the host has.
- **Workboard** (bundled, disabled by default): Kanban cards with parent→child dependencies,
  claims + heartbeats, retry budget and runtime limit per card, `workboard_complete/block`, a
  protocol-violation block when a worker stops without completing, dispatch through the Gateway
  sub-agent runtime, and a durable notification cursor
  ([docs/plugins/workboard.md L141-300](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/workboard.md#L141-L300)).
  "It is not a replacement for GitHub Issues" — still LLM-routed, no CI wait.
- **Managed worktree sessions**: `sessions.create {worktree: true, worktreeBaseRef, worktreeName}`
  (new in 2026.9.7 "Worktree sessions", [CHANGELOG L16](https://github.com/openclaw/openclaw/blob/v2026.9.9/CHANGELOG/2026.9.7.md#L16)) — a native S2.
- **Decision models**: `decision_evaluate` tool for Boolean/Choice/Score questions against a
  configured decision model (2026.9.7, [CHANGELOG L48](https://github.com/openclaw/openclaw/blob/v2026.9.9/CHANGELOG/2026.9.7.md#L48)) —
  a possible structured-verdict primitive for S7 (**inferred**, not examined).
- **Codex supervision** (opt-in, `codex` plugin): lists non-archived native Codex CLI/VS Code
  sessions from the host in the OpenClaw sidebar and can branch them into a Chat
  ([docs/plugins/codex-supervision.md](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/plugins/codex-supervision.md)).
  If the LangGraph prototype drives Codex under a user-home `CODEX_HOME`, OpenClaw could later
  *show* those builder/reviewer sessions without owning them (**inferred**).
- In this repo (**verified locally**): `versions.lock.json` pins `openclaw.tag = v2026.9.9` with
  extensions `diagnostics-prometheus`, `codex`, `google-workspace` (no `lobster`, no `acpx`), and the
  backlog-autonomy design already uses a recurring **command job** that `docker run`s the ops
  image (`oc2-backlog-poll`, `docs/design/backlog-autonomy/README.md` ~L189).

---

## 7. Synthesis

### 7a. OpenClaw-native baseline for S1–S10 (what you would build without LangGraph)

| Step | Closest native mechanism at v2026.9.9 | Deterministic? | Gap |
|---|---|---|---|
| S1 Intake | agent turn running `gh issue view`; or a condition-watcher script that checks for an "Acceptance criteria" section | watcher: yes; turn: no | asking a human = chat/`ask_user`; no typed gate |
| S2 Workspace | `sessions.create {worktree:true}` (managed worktree) | yes (RPC) | WS RPC only, not in Admin HTTP RPC allowlist |
| S3 Build | builder agent turn (Codex harness or OpenClaw runtime), or ACP `claude`/`codex` | no (by design) | — |
| S4 Local gate | command/script automation, or a Lobster pipeline the LLM calls | partly | nothing routes a failure back to S3 except an LLM or a fired agent turn |
| S5 Publish | `github_publish` → `sessions.github.publish` (Gateway-held creds, draft PR) | yes once called | called by the LLM, or by WS RPC |
| S6 CI wait | condition watcher (`trigger.script`, e.g. `gh pr checks`) firing an agent turn on change | yes | min 30 s cadence, 5 tool calls/30 s per check; fired turn is LLM |
| S7 Review | reviewer agent turn (sub-agent / ACP) | no | no enforced verdict schema (maybe `decision_evaluate`) |
| S8 Fix loop | conductor LLM + `sessions_spawn`, or Workboard retry budgets | no | **this is exactly today's brittle prose state machine** |
| S9 Merge-ready | agent runs `gh pr ready` | no | — |
| S10 Escalate | chat channels, approvals, Lobster approval tokens, `/hooks/wake` | partly | no graph-level interrupt/resume |
| X Resume | SQLite transcripts; interrupted main-session turns auto-resume; cron/subagent/ACP sessions are *not* resumed by that path | partly | no workflow checkpoint since TaskFlow removal |
| X Alerts | cron failure alerts (2 failures, 1 h cooldown), auto-disable at 10 | yes | — |
| X Secrets | `github_publish` keeps creds on Gateway; but `gh`/`GH_TOKEN`/user home are visible to agents by default | — | must be engineered per host |

Verdict (**inferred**): after the TaskFlow removal there is **no native declarative, durable,
multi-step engine** in OpenClaw. A native baseline would still need an LLM to sequence S3→S9, i.e.
the current conductor. Useful native *parts* (worktree sessions, `github_publish`, condition
watchers, automations alerting) reduce LLM routing but do not remove it. This supports building the
graph outside OpenClaw (LangGraph) and treating OpenClaw as host and human interface.

### 7b. How OpenClaw could host/supervise an external LangGraph workflow later

Ranked by fit (all **inferred** designs built on **verified** primitives above):

1. **Recurring command job that ticks the graph** (`openclaw automations add --every 5m
   --command-argv '["docker","run",…,"python","-m","wf","tick"]' --timeout-seconds 600
   --no-deliver` + `failureAlert`). Each tick resumes every non-terminal LangGraph thread from its
   checkpointer, advances it until it blocks (CI pending, waiting for a human, budget hit), and exits.
   Pros: matches the repo's existing `oc2-backlog-poll` pattern; nothing long-lived to supervise; a
   crash just means the next tick resumes; run history + failure alerts + auto-disable for free; env
   is explicit via `docker run -e`. Cons: CI wait granularity = tick interval; one slot of 8 while running.
2. **Stream schedule as a keep-alive supervisor** (`--stream-command '["python","-m","wf","worker"]'
   --stream-mode match --stream-match '^WF_EVENT '` with a script or agent-turn payload that posts
   merge-ready/blocked events to the operator channel). Pros: real restart-on-crash with back-off,
   stdout→event bridge, alerts after 5 short runs. Cons: inherits the full Gateway env; restarts on
   *clean* exit too (worker must be a daemon or the job must be disabled at the end); stopped and
   restarted on every Gateway restart/update (fine with checkpoints if side effects are idempotent);
   whether stream sources count against the 8-run cron cap is not verified.
3. **Notifications and human answers**: graph → OpenClaw via `POST /hooks/wake` (short trusted
   event into the main session) or `/hooks/agent` (`deliver` to a channel); human → graph is the
   weak link: hooks return no text, so the answer must come back via WS `chat.history`
   polling, a GitHub issue comment, or an agent tool writing to the graph's store.
4. **Agent steps executed by OpenClaw** (optional): a LangGraph node calls `openclaw agent exec
   --cwd <worktree> --json` (no Gateway) or WS `agent` + `agent.wait` against dedicated
   builder/reviewer agents, so OpenClaw keeps owning the Codex OAuth profile, harness, sandbox and
   tool policy while the graph owns routing. The `/v1/chat/completions` endpoint can do the same
   but holds an HTTP request for the whole turn and requires a full-operator token.
5. **Not recommended**: Lobster (short in-Gateway tool call, 20 s default, no LLM steps, no loops,
   not installed in our build), ACP for S3/S7 (adds a layer without adding determinism), CLI
   backends (text-only fallback), using OpenClaw as a raw model proxy for LangGraph.

### 7c. Recommendation

- Prototype on the Mac **without** depending on OpenClaw. Keep an "agent-step backend"
  interface in the graph so S3/S7 can later switch between a direct Codex CLI/app-server call and
  `openclaw agent exec`/WS `agent` without touching routing.
- Copy two OpenClaw patterns into the prototype: (1) Codex under an isolated `CODEX_HOME` with
  a scrubbed env, and no `GH_TOKEN`/`gh` login reachable from the agent's `HOME`; (2) a deterministic
  publish step that alone holds GitHub credentials (OpenClaw's `github_publish` does the same).
- For the later host: option 1 (recurring command job ticking a checkpointed graph) first, option 2
  only if tick latency becomes a problem; `/hooks/wake` for operator notifications.

---

## 8. Open questions (not verified here)

1. Do stream-schedule source processes count against `DEFAULT_CRON_MAX_CONCURRENT_RUNS = 8`?
2. When the Gateway restarts, is a running **command-job** child killed (process tree) or orphaned?
   Docs say interrupted runs are recorded as failures; child fate not checked.
3. Exact `sessions.github.publish` contract (branch naming, push remote, shared vs personal account,
   scopes, idempotency) and whether an external WS client with `operator.write` may call it for a
   session it created.
4. Semantics of the `agent` RPC's `swarmCollector` / `swarmOutputSchema` (possible structured output).
5. Whether `openclaw agent exec` with the Codex harness confines Codex-native shell/file tools to
   `--cwd` (Codex sandbox) or only OpenClaw's own filesystem tools; and whether `HOME`-based `gh`
   credentials leak into it (docs suggest they do for app-server launches).
6. SIWC is OpenClaw's own OAuth app registration; a separate Python workflow cannot (and should not)
   reuse it — a separate Codex login (own `CODEX_HOME`) is the clean path. Confirm with the
   LLM-access research thread.
