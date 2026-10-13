# 04 — Durability, supervision, packaging ("canned workflow container") and observability

Research date: 2026-10-13. Status: COMPLETE (sections 1–7). Sources fetched 2026-10-13 unless noted.

Legend: **verified** = read in a primary source (link given; version/date noted); **inferred** = my reasoning or
an unconfirmed secondary source.

## Summary (read this first)

- **Durability is real but not exactly-once.** LangGraph checkpoints every super-step (default `durability="async"`;
  use `"sync"`), keeps per-node "pending writes", and resumes with `invoke(None, cfg)`. After a crash the interrupted
  node re-runs **from its start**; an open, maintainer-unanswered report (#8039) says even `"sync"` can re-execute a
  finished node after SIGKILL. → Every side-effecting node (worktree, push, PR, comments, ready-for-review) must be check-before-act; keep
  an "accepted runs" ledger written before the first invoke (#8764).
- **LangGraph 1.2 (2026-05) added what we need for supervision inside the graph:** per-node `RetryPolicy`,
  `TimeoutPolicy(run_timeout, idle_timeout, heartbeat)` (async nodes only), `error_handler` → route to Blocked,
  `set_node_defaults`, and cooperative shutdown (`RunControl.request_drain()` → `GraphDrained`).
- **Waits:** CI (5–60 min) — poll inside the node with heartbeats; human answers (days) — `interrupt()` and exit,
  resume with `Command(resume=…)`. Open SWE's `/baby-sit` shows the exit-and-reinvoke alternative (10-min crons +
  check-run webhooks + dedup keys).
- **Runtime:** the plain MIT library + `AsyncSqliteSaver` in our own process (launchd on the Mac, a container with
  `restart: unless-stopped` on Linux) is the right prototype. `langgraph dev` is a debugging server (Elastic-2.0,
  in-memory + pickles; had a no-flush data-loss bug). The Agent Server needs Postgres + Redis, a LangSmith key, a
  licence for production and phones home; **Aegra** (Apache-2.0) is the open-source Agent Protocol alternative if we
  later want an HTTP control plane. DeerFlow (83.8k stars) also runs its own runtime on the library.
- **Packaging:** one `oc2-workflow` image with graph + pinned Codex CLI + persistent `CODEX_HOME` (ChatGPT login
  refreshed in place, one consumer per `auth.json`), deterministic nodes hold GitHub credentials, `codex exec` runs in
  per-task sandbox containers without GitHub tokens; OpenClaw cron command jobs call `oc2wf tick/status --json`.
- **Observability with zero egress by default:** LangSmith SDK tracing is off unless `LANGSMITH_TRACING=true`, but
  the Agent Server defaults it **on**, the `langgraph` CLI sends analytics (`LANGGRAPH_CLI_NO_ANALYTICS=1`), Codex
  sends metrics to Statsig by default, Langfuse/Phoenix send usage telemetry by default — all switchable. Use JSONL +
  checkpoint history, optionally OTel → Phoenix/Langfuse self-hosted.

Note: links to `bodegus/openclaw2-deploy` point to a private repository.

## Contents
1. Checkpointing and resume (X, S5, S6, S10)
2. Long waits: keep-alive polling vs exit-and-reinvoke (S6, S10)
3. Running it: launchd, `langgraph dev`, Agent Server, licensing, canned containers
4. Supervision: health, stuck runs, restart, external control API/CLI
5. Observability without third-party egress
6. Recommendation: (a) Mac prototype, (b) Linux + rootless Docker next to OpenClaw
7. Open questions

---

## Versions seen (PyPI JSON API, 2026-10-13)

| Package | Version (upload date) | Licence | Notes |
|---|---|---|---|
| `langgraph` | 1.2.15 (2026-10-12); 1.0.0 was 2025-10-17, 1.1.0 2026-03-10, 1.2.0 2026-05-12 | MIT | Python >=3.10 |
| `langgraph-checkpoint` | 4.3.0 (2026-10-12) | MIT | base interface + `InMemorySaver`, serde, `EncryptedSerializer` |
| `langgraph-checkpoint-sqlite` | 3.1.2 (2026-10-12) | MIT | deps: `aiosqlite`, `sqlite-vec` |
| `langgraph-checkpoint-postgres` | 3.1.3 (2026-10-12) | MIT | deps: `psycopg>=3.2`, `psycopg-pool` |
| `langgraph-cli` | 0.4.33 (2026-10-07) | MIT | `langgraph dev/up/build/dockerfile` |
| `langgraph-api` | 0.16.0 (2026-10-10) | **Elastic-2.0** | the Agent Server itself (not OSS-licensed) |
| `langgraph-runtime-inmem` | 0.36.0 (2026-10-10) | **Elastic-2.0** | in-memory runtime used by `langgraph dev` |
| `langgraph-sdk` | 0.4.7 (2026-10-12) | MIT | HTTP client for Agent Server |
| `langsmith` | 0.14.8 (2026-10-13) | MIT | tracing client (also used for OTel export) |
| `langfuse` | 4.17.0 (2026-10-05) | MIT (SDK) | self-hostable tracing |

Repos (via `gh api`, 2026-10-13): `langchain-ai/langgraph` 43.2k stars, MIT, pushed 2026-10-13, maintained;
`langchain-ai/open-swe` 11.0k, MIT, pushed 2026-10-13, maintained; `langchain-ai/deepagents` 30.2k, MIT, maintained;
`openai/codex` 129k, Apache-2.0, maintained; `openai/codex-universal` 1.1k, MIT (in `LICENSES/LICENSE`; GitHub's detector shows none), last push 2026-05-02;
`langfuse/langfuse` 35.7k, MIT core + `ee/` folders (NOASSERTION in GitHub's detector), maintained.
Pinned source commit used for permalinks below: `langchain-ai/langgraph@afbe7e4` (2026-10-12, "release(checkpoint-postgres): 3.1.3").

---

## 1. Checkpointing and resume (X; S5/S6/S9 idempotency; S10 interrupts)

### 1.1 How checkpoints work (verified)

- A checkpoint is written at every **super-step** boundary; inside a super-step each finished node's writes are
  stored as **pending writes** (`checkpoint_writes`/`writes` table) so that, if a sibling node fails, the
  successful ones are not re-run on resume. Source: [Checkpointers docs](https://docs.langchain.com/oss/python/langgraph/checkpointers)
  ("Super-steps", "Pending writes"; page fetched 2026-10-13). **verified**
- `thread_id` (in `config["configurable"]`) is the primary key; `checkpoint_id` selects a historical snapshot;
  `checkpoint_ns` separates subgraphs. `graph.get_state(config)` returns a `StateSnapshot` with `values`, `next`
  (nodes to run next; `()` = finished), `tasks` (each with `error`, `interrupts`), `metadata.step`, `created_at`.
  `graph.get_state_history(config)` lists all snapshots newest-first. Same page. **verified**
- `update_state(config, values, as_node=...)` writes a *new* checkpoint (source `"update"`) — useful for an operator
  to patch state (e.g. bump a loop counter, inject a human answer) before resuming. **verified** (same page)
- Replay/fork ("time travel"): invoking with an old `checkpoint_id` re-executes every node *after* it, including
  LLM calls and interrupts; nodes before it are not re-run. [Use time-travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel). **verified**
  → For us: time travel is a debugging/repair tool, *not* a safe "undo" — re-running S5 from an old checkpoint
  would re-push. Publishing nodes must be idempotent (1.4).

### 1.2 Durability modes (verified)

`graph.invoke/stream(..., durability="sync"|"async"|"exit")`:

- `"exit"` — persist only when the run exits (success, error, interrupt). No crash recovery mid-run.
- `"async"` — **the default** — persist while the next step runs; small window where a crash loses the latest checkpoint.
- `"sync"` — persist before starting the next step.

Docs: [Checkpointers → Durability modes](https://docs.langchain.com/oss/python/langgraph/checkpointers#durability-modes). Default `"async"` in code:
[`pregel/main.py#L2695-L2696`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/langgraph/langgraph/pregel/main.py#L2695-L2696);
type [`types.py#L98`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/langgraph/langgraph/types.py#L98). **verified**

Our pipeline has few, slow, expensive super-steps (a builder loop is minutes; CI is minutes), so checkpoint
overhead is irrelevant: **use `durability="sync"`**. **inferred**

Caveat (open bug, verified): [langgraph#8039](https://github.com/langchain-ai/langgraph/issues/8039) (open, 51 comments,
created 2026-06-10) reports that even under `"sync"` the order of `put_writes` (a finished task's writes) and `put`
(the next checkpoint) is not enforced, so after a `SIGKILL` a completed node can be **re-executed** instead of
replayed; two community fix PRs (#8050, #8055) were closed unmerged. Related:
[#8764](https://github.com/langchain-ai/langgraph/issues/8764) (open) — a crash *before the first checkpoint* leaves
no trace at all, and `invoke(None, config)` then raises `EmptyInputError`; the reporter asks for documentation
that "callers must provide their own acceptance ledger". [#9002](https://github.com/langchain-ai/langgraph/issues/9002)
(open) — a node-level `error_handler` can run twice on resume.
→ Design rule: **every side-effecting node must be safe to run twice**, and the runner keeps its own tiny
"accepted runs" ledger (issue number → thread_id → status) written *before* the first `invoke`. **inferred**

### 1.3 SQLite vs Postgres checkpointers

| | `SqliteSaver` / `AsyncSqliteSaver` (`langgraph-checkpoint-sqlite` 3.1.2) | `PostgresSaver` / `AsyncPostgresSaver` (`langgraph-checkpoint-postgres` 3.1.3) |
|---|---|---|
| Positioning | "lightweight, synchronous use cases (demos and small projects) and does not scale to multiple threads" — [class docstring](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py#L50-L57); docs: "Ideal for experimentation and local workflows" | "used in LangSmith. Ideal for using in production" ([docs](https://docs.langchain.com/oss/python/langgraph/checkpointers#checkpointer-libraries)) |
| Setup | `setup()` auto-called; runs `PRAGMA journal_mode=WAL` and creates `checkpoints` + `writes` tables ([L134-L170](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py#L134-L170)); a `threading.Lock` serialises access | **must** call `setup()` yourself; it applies numbered `MIGRATIONS` tracked in `checkpoint_migrations` ([`__init__.py#L85-L108`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py#L85-L108), [`base.py#L44`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/checkpoint-postgres/langgraph/checkpoint/postgres/base.py#L44)) |
| Connection | `SqliteSaver.from_conn_string("checkpoints.sqlite")` (context manager) or `SqliteSaver(sqlite3.connect(path, check_same_thread=False))` | `PostgresSaver.from_conn_string(url)` opens with `autocommit=True, prepare_threshold=0, row_factory=dict_row` ([L64-L83](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py#L64-L83)) — a hand-made pool must use the same options |
| Ops | one file; back up with `sqlite3 .backup`; one writer process | needs a Postgres container; `thread_id` < 255 chars ([persistence troubleshooting](https://docs.langchain.com/oss/python/langgraph/persistence)) |
| Maintainer warning | `AsyncSqliteSaver` docstring: "not recommended for production workloads due to limitations in SQLite's write performance. For production use, consider a more robust database like PostgreSQL" ([aio.py#L57-L60](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py#L57-L60)); needed for async graphs (node timeouts are async-only, §1.5) | pool via `psycopg_pool`; `AsyncPostgresSaver` for async graphs |
| Retention | `delete_thread(thread_id)` exists in both; no built-in TTL in the library — docs suggest "a cron job to delete checkpoints older than N days" ([persistence](https://docs.langchain.com/oss/python/langgraph/persistence)) | same |

Both support encryption at rest via `EncryptedSerializer.from_pycryptodome_aes()` (key from `LANGGRAPH_AES_KEY`)
([checkpointers → Encryption](https://docs.langchain.com/oss/python/langgraph/checkpointers#encryption)). **verified**
Other backends listed in [checkpointer integrations](https://docs.langchain.com/oss/python/integrations/checkpointers/index):
MongoDB, Redis (`langgraph-checkpoint-redis` 0.5.2, MIT, redis-developer), AWS, CockroachDB, etc. **verified**

**Assessment (inferred):** one workflow process, one to three concurrent issues, a few super-steps per hour — the
maintainers' warning is about SQLite *write throughput*, which we will not approach, so SQLite (WAL, one file on a
volume) is enough for the Mac prototype and acceptable for a single-process Linux deployment. Switch to Postgres
(`AsyncPostgresSaver`, same API — keep the checkpointer behind a factory) when any of these becomes true: more than
one worker process writes checkpoints; or we adopt an Agent Protocol server (Aegra and the Agent Server both require
Postgres, §3.3–3.4). (SQLite's online `.backup` works while the worker runs, so backups are not a reason.)

### 1.4 What exactly re-runs after a crash (verified + inferred)

Resume = call the graph again with the same `thread_id` and **`None` input** (`graph.invoke(None, config)`), or with
`Command(resume=...)` if it is paused at an `interrupt`. Documented for drain/resume in
[Fault tolerance → Resume after drain](https://docs.langchain.com/oss/python/langgraph/fault-tolerance#resume-after-drain). **verified**

- **Graph API nodes re-run from the start of the node function**: "the affected node runs again from the start of
  its function. Code and side effects before the pause run again." —
  [Graph API → Re-execution and idempotency](https://docs.langchain.com/oss/python/langgraph/graph-api#re-execution-and-idempotency). **verified**
- Nodes that already finished in the same super-step are skipped via pending writes (but see #8039 above). **verified**
- **Inside a node**, sub-steps wrapped as `@task` are individually checkpointed; on resume completed task results
  are restored and only unfinished tasks run again ("Using tasks in nodes", same page). "A task that started but
  did not finish may run again on that resume, so design side effects to be idempotent" —
  [Functional API → Idempotency](https://docs.langchain.com/oss/python/langgraph/functional-api#idempotency). **verified**
- Functional API `@entrypoint` replays its body from the top, restoring `@task` results **by call position** —
  adding/reordering tasks before the resume point breaks in-flight runs; anything non-deterministic must be in a
  task ([Functional API → Determinism](https://docs.langchain.com/oss/python/langgraph/functional-api#determinism)). **verified**
- `interrupt()` re-runs the whole node on resume; "Side effects called before `interrupt` must be idempotent"
  ([Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts#side-effects-called-before-interrupt-must-be-idempotent)). **verified**

Implications for our steps (**inferred**):

| Step | Crash mid-node → on resume | Make it safe by |
|---|---|---|
| S2 Workspace | node re-runs | `git worktree add` only if path absent; branch name derived from issue number (`agent/issue-123`), so re-run is a no-op |
| S3 Build (agent loop, 5–60 min) | **whole agent loop restarts** unless the loop itself checkpoints | run the builder as a *subgraph* (Deep Agents / `create_agent` are LangGraph graphs) so its own steps checkpoint under `checkpoint_ns`, or accept a restart (worktree keeps partial edits; prompt the builder with `git diff`) |
| S4 Local gate | re-runs tests | naturally idempotent |
| S5 Publish | may re-run push/PR create | check-before-act: `git push` of the same SHA is a no-op; before creating a PR, `GET /repos/{o}/{r}/pulls?head=owner:branch&state=open`; GitHub also rejects a duplicate head/base PR with **422 "A pull request already exists for …"** ([go-github#1441](https://github.com/google/go-github/issues/1441)). Store `pr_number` + pushed `head_sha` in state |
| S6 CI wait | re-polls | idempotent read; key everything on `head_sha` |
| S7 Review | reviewer loop restarts | idempotent if the verdict is only written to state; post review comments in a separate node with check-before-act (search for a marker like `<!-- run:{thread_id}:round:{n} -->`) |
| S9 Merge-ready | may re-mark ready / re-post summary | read `isDraft` first and call GraphQL `markPullRequestReadyForReview` only if still draft; summary comment guarded by a hidden marker |
| S10 Escalate | node re-runs up to `interrupt()` | post the question *after* the interrupt is answered, or guard with a marker; the question itself goes to the human via the runner, not inside the node |

Optional belt and braces: wrap the GitHub calls in `@task` (Graph API nodes may call tasks) so a completed push/PR
call is restored rather than redone if a *later* step in the same node crashes. **verified mechanism / inferred fit**

### 1.5 Node-level timeouts, retries, error handlers, graceful shutdown (langgraph >= 1.2, verified)

From [Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) (fetched 2026-10-13):

- `add_node(..., retry_policy=RetryPolicy(max_attempts=3, ...))` — default `retry_on` skips `ValueError`, `OSError`,
  etc.; for `requests`/`httpx` only 5xx is retried.
- `add_node(..., timeout=TimeoutPolicy(run_timeout=..., idle_timeout=..., refresh_on="auto"|"heartbeat"))` —
  **async nodes only**; idle clock is reset by stream output, LangChain callback events (LLM tokens, tool calls) or
  explicit `runtime.heartbeat()`. Raises `NodeTimeoutError` (retryable by default). → built-in **stuck detection**
  for the builder/reviewer nodes (e.g. `idle_timeout=600`, `run_timeout=5400`).
- `add_node(..., error_handler=fn)` — after retries are exhausted, `fn(state, error: NodeError) -> Command(goto=...)`;
  `set_node_defaults(...)` sets these graph-wide. "Failure provenance is checkpointed" so the handler sees the same
  error after a crash (but see #9002). → route any unexpected failure to S10 Blocked.
- `runtime.execution_info.node_attempt`, `.thread_id`, `.run_id` are available inside nodes.
- **Graceful shutdown**: `control = RunControl(); graph.invoke(inputs, config, control=control)`; a SIGTERM handler
  calls `control.request_drain("sigterm")`; the run stops at the next super-step boundary and raises
  `GraphDrained`; resume later with `graph.invoke(None, config)`. A node that is mid-execution "runs to completion"
  first; `runtime.drain_requested` lets a long node bail out early. Source:
  [`runtime.py#L79-L105`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/langgraph/langgraph/runtime.py#L79-L105),
  [`errors.py#L55-L66`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/langgraph/langgraph/errors.py#L55-L66).
- Recursion limit default 1000 super-steps since 1.0.6; `RemainingSteps` lets a graph end gracefully
  ([Graph API → Recursion limit](https://docs.langchain.com/oss/python/langgraph/graph-api#recursion-limit)).
  Our bounded loops (S4 ≤ N, S6 ≤ N, S8 ≤ 3) should be explicit counters in state, with `recursion_limit` as a backstop.

### 1.6 Changing graph code while runs are in flight ("migration") — verified

[Backward compatibility](https://docs.langchain.com/oss/python/langgraph/backward-compatibility) and
[Graph API → Graph migrations](https://docs.langchain.com/oss/python/langgraph/graph-api#graph-migrations):

- LangGraph does **not** pin a run to the code version it started with; resumed threads run the *current* graph.
- Edges are not persisted → adding/removing/rerouting edges is safe. **Renaming/removing a node** breaks threads
  paused at/about to enter it. Adding state keys is safe (make them `NotRequired`); renamed keys lose their value;
  incompatible type changes "could currently cause issues".
- Pattern for business-logic changes: stamp `flow_version` into state at intake and branch on it.
- Functional API: never insert/reorder `@task`/`interrupt` calls before a resume point; or register a new
  entrypoint under a new name in `langgraph.json`.
- Finding in-flight threads: with the Agent Server, `threads.search(status="interrupted"|"busy")`; self-run: keep
  our own run ledger (LangGraph has no index over thread state).

→ For us (**inferred**): keep node names stable (`intake`, `workspace`, `build`, `local_gate`, `publish`, `ci_wait`,
`review`, `merge_ready`, `blocked`), put `flow_version` in state from day one, and drain/finish in-flight runs
before renaming nodes.

### 1.7 Examples of check-before-act / durable side effects in the wild

1. LangGraph docs' own idempotency guidance: upsert / read-before-write / idempotency keys
   ([graph-api](https://docs.langchain.com/oss/python/langgraph/graph-api#re-execution-and-idempotency),
   [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts#side-effects-called-before-interrupt-must-be-idempotent)). **verified**
2. Crash-injection harness referenced in #8039/#8764 (community, `mstevens843/crashpoint`) — shows the
   SIGKILL-at-`put()` methodology for testing our own nodes. **verified (exists, linked from issue)**; not evaluated.
3. Open SWE (see §3.6) stores the sandbox ID in thread metadata and reconnects to it on the next run instead of
   creating a new sandbox — a check-before-act pattern for the S2 workspace. (verified in §3.6)

### 1.8 Making the S3/S7 agent loops themselves crash-resumable (verified mechanisms, inferred design)

A Graph-API node re-runs from its start after a crash (§1.4), so a 40-minute builder loop would restart from zero.
With the Codex CLI as the loop:
- `codex exec --json` emits JSONL events (`thread.started` with a `thread_id`, `turn.started`, `turn.completed`,
  `turn.failed`, `item.*`, `error`), and `codex exec resume <SESSION_ID> "<prompt>"` continues a previous session
  ([Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)). `--output-schema schema.json` makes the
  final message conform to a JSON Schema (useful for the S7 verdict). **verified**
- Design: the S3 wrapper writes the Codex session id to the run ledger (outside graph state) the moment
  `thread.started` arrives, and calls `runtime.heartbeat()` on every JSONL line (idle-timeout stuck detection, §1.5).
  On resume the node finds the session id and runs `codex exec resume <id> "Continue; the workflow restarted."`
  against the same worktree instead of starting over. **inferred** (assumes the `thread_id` in `thread.started` is the
  `<SESSION_ID>` that `resume` accepts — the docs show both but do not say so explicitly; verify)
- Same idea in LangGraph-native agents: run the builder as a *subgraph* (Deep Agents / `create_agent` graphs) so its
  model/tool steps checkpoint under their own `checkpoint_ns` and resume mid-loop. **inferred** (mechanism verified in
  [subgraphs/checkpoint namespace](https://docs.langchain.com/oss/python/langgraph/checkpointers#checkpoint-namespace)).
- Codex docs also warn: "Do not set `OPENAI_API_KEY` or `CODEX_API_KEY` as a job-level environment variable in
  workflows that check out or run repository-controlled code" — the same reasoning applies to a ChatGPT `auth.json`
  readable by the sandbox. **verified**

---

## 2. Long waits: keep a process alive and poll, or exit and re-invoke? (S6, S10)

### 2.1 What LangGraph gives you (verified)

- **`interrupt()` is the only first-class "wait"**: state is checkpointed and the graph "waits indefinitely until you
  resume execution" — the caller's `invoke` *returns*; nothing has to stay alive
  ([Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)). Resume = `invoke(Command(resume=value), config)`
  from any process, any time later. With Agent Server the thread status becomes `interrupted`
  ([Use threads → filter by status](https://docs.langchain.com/langsmith/use-threads)) and "An interrupt for
  human-in-the-loop creates a separate Deployment Run when resuming" ([FAQ](https://docs.langchain.com/langsmith/faq)),
  i.e. the first run has ended. **verified**
- **No durable timer / "sleep until" primitive.** I found no `sleep_until`/timer API in the LangGraph or Agent Server
  docs index (searched 2026-10-13). Waiting on time therefore means either an in-process loop or an external
  scheduler. **verified by absence (weak)**
- In-process polling is supported by the 1.2 node timeouts: `TimeoutPolicy(idle_timeout=..., refresh_on="heartbeat")` +
  `runtime.heartbeat()` per poll ([Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance#manual-heartbeats)). **verified**

### 2.2 Option A — keep the process alive and poll inside the node

```python
async def ci_wait(state, runtime):              # S6, no LLM
    deadline = state["ci_deadline"]            # stamped once in state by the previous node (deterministic on replay)
    while True:
        checks = await gh.check_runs(state["head_sha"])   # GET /repos/{o}/{r}/commits/{sha}/check-runs
        runtime.heartbeat()
        if checks.all_completed:
            return {"ci": checks.summary()}
        if time.time() > deadline:
            return {"ci": {"state": "timeout"}}
        await asyncio.sleep(30)
builder.add_node("ci_wait", ci_wait, timeout=TimeoutPolicy(run_timeout=90*60, idle_timeout=300, refresh_on="heartbeat"))
```
(**inferred** sketch.) Crash during the wait → resume re-enters the node and simply polls again (idempotent read).
Pros: simplest, no extra infrastructure, CI latency ≤ poll interval. Cons: a process (and on the Agent Server a worker
slot, `N_JOBS_PER_WORKER`) is held for 5–60 min per PR; human waits of days cannot be done this way.

Examples: (1) the docs' heartbeat example ([fault-tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance#manual-heartbeats));
(2) `gh pr checks --watch` / `gh run watch` from a subprocess (same shape, external tool);
(3) on the Agent Server a run may hold a worker for up to `BG_JOB_TIMEOUT_SECS` (default 86400 s) —
[env vars](https://docs.langchain.com/langsmith/env-var-self-hosted). **verified (1, 3) / inferred (2)**

### 2.3 Option B — exit and re-invoke on a schedule or webhook

Pattern: S6 node records `head_sha` and calls `interrupt({"kind": "ci_wait", "head_sha": ...})`; the run ends.
A small **sensor** (cron/launchd tick or a GitHub `check_suite`/`workflow_run` webhook) finds threads waiting on CI,
asks GitHub once, and resumes the ones whose CI is finished with `Command(resume={"conclusion": ..., "failed_logs": ...})`.
Human answers (S10) are the same shape: the reply handler resumes the thread.

Examples:
1. **Open SWE `/baby-sit`** (langchain-ai/open-swe, MIT, 11.0k stars, pushed 2026-10-13): "Durable, opt-in PR CI
   watches" — an Agent Server **cron** every 10 minutes per watched PR (`client.crons.create("scheduler", schedule="*/10 * * * *")`)
   **plus** `check_run`/`check_suite` webhooks, deduplicated by GitHub delivery ID, guarded by a TTL'd lock thread,
   with a dispatch fingerprint `sha256(head_sha|retry_count)` and `MAX_RETRIES_PER_HEAD = 3`
   ([`openswe/baby_sit.py#L40-L48`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/baby_sit.py#L40-L48),
   [`#L151-L163`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/baby_sit.py#L151-L163),
   [`#L386-L410`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/baby_sit.py#L386-L410),
   [`#L537-L586`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/baby_sit.py#L537-L586)). **verified**
   Its `aggregate_check_state()` → `pending | success | blocked | failure` is a good model for S6.
2. **Agent Server run-completion webhooks**: `POST /threads/{id}/runs` (and crons, wait/stream) accept `webhook=<url>`
   and the server POSTs when the run completes ([Use webhooks](https://docs.langchain.com/langsmith/use-webhooks));
   Open SWE consumes these at `/webhooks/run-complete` with a token check
   ([`openswe/api/health.py`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/api/health.py)). **verified**
3. **Agent Server / Aegra cron jobs** (`client.crons.create(...)`, UTC schedules, stateless or thread-bound)
   ([Use cron jobs](https://docs.langchain.com/langsmith/cron-jobs); Aegra: "at-least-once … ensure scheduled work is
   idempotent" — [docs.aegra.dev/guides/cron](https://docs.aegra.dev/guides/cron)). **verified**
4. **Plain launchd/cron tick** for a self-run Python process: `StartInterval`/`StartCalendarInterval`. macOS caveats
   from `man launchd.plist` (macOS 26.7.1): with `StartInterval` "If the system is asleep … that interval will be
   missed" and "If the job is running during an interval firing, that interval firing will likewise be missed"
   (free mutual exclusion); `StartCalendarInterval` instead coalesces missed firings and runs on wake. **verified**

Pros: no process held during CI or human waits; restarts are trivial (nothing in flight between ticks); the same
sensor handles "PR closed by a human", "new push by a human", "review comment posted". Cons: more moving parts
(sensor, dedup, locks), latency = tick interval unless webhooks are added; webhooks need a public endpoint
(the Mac has none — use polling there).

### 2.4 Recommendation (inferred)

- **S6 CI wait:** start with **Option A** (poll inside the node, 30–60 s interval, `idle_timeout` heartbeat, hard
  `run_timeout` ~90 min → route to S10 "CI timeout"). It is deterministic, has no LLM, and needs nothing else on a Mac.
  Concurrency is bounded by how many issues run at once (a few), so held processes are cheap.
- **S10 human answer:** always **Option B** via `interrupt()`. The runner exits; a reply handler (CLI command, GitHub
  issue-comment poll, or later an OpenClaw automation) resumes with `Command(resume=answer)`.
- Keep the S6 node's *interface* compatible with Option B (`interrupt` payload `{"kind":"ci_wait","head_sha":…}`), so
  that on the Linux host we can switch to a sensor/webhook without changing graph topology (a node rename would break
  paused threads, §1.6).

---

## 3. Running it

### 3.1 Option R1 — plain Python process + library checkpointer (launchd on the Mac)

What it is: `python -m wf run --issue 123` (or a long-lived `wf serve` loop) that compiles the graph with
`SqliteSaver`/`PostgresSaver` and calls `invoke(...)` / `invoke(None, config)` / `invoke(Command(resume=...))`.
Everything is MIT-licensed open source (`langgraph`, `langgraph-checkpoint-*`). No LangSmith account, no licence key,
no Redis. **verified** (licences: see "Versions seen")

Supervision on macOS with launchd (`~/Library/LaunchAgents/*.plist`; semantics from `man launchd.plist`, macOS 26.7.1, **verified**):
- `KeepAlive` = `true` or `{SuccessfulExit: false}` (restart only on non-zero exit) or `{Crashed: true}`; jobs that exit
  quickly are throttled — `ThrottleInterval` default 10 s.
- `ExitTimeOut` = seconds between SIGTERM and SIGKILL on stop → pair with LangGraph `RunControl.request_drain()` in
  a SIGTERM handler so the run stops at a super-step boundary (§1.5).
- `StartInterval` (tick every N s; missed while asleep or while the previous tick still runs) or
  `StartCalendarInterval` (coalesced after wake) for a "tick" design.
- `StandardOutPath`/`StandardErrorPath` for logs; `EnvironmentVariables`, `WorkingDirectory`.

Two shapes (**inferred**):
- **Long-lived worker** (`KeepAlive`): one process owns all active threads (asyncio tasks), polls CI in-node, exposes a
  local CLI/HTTP for status. On restart it lists non-finished threads from its ledger and calls `invoke(None, …)` for
  each that is not waiting on an interrupt.
- **Tick** (`StartInterval=60`): each tick loads the ledger, advances every thread by "one wait" (resume the ones
  whose CI finished or whose human answered), starts new issues up to a WIP limit, then exits. Crash-safety is
  maximal (nothing in flight between ticks) but an S3 builder loop of 30 min would hold one tick for 30 min — fine,
  because launchd skips overlapping firings.

### 3.2 Option R2 — `langgraph dev` (in-memory Agent Server)

- `pip install "langgraph-cli[inmem]"`; serves the Agent Server API on `127.0.0.1:2024` without Docker; hot reload;
  "State persistence: In-memory & pickled to local directory"
  ([Local development & testing](https://docs.langchain.com/langsmith/local-dev-testing)). **verified**
- The runtime packages `langgraph-api` and `langgraph-runtime-inmem` are **Elastic-2.0**, and their source is not in
  the public monorepo (a contributor could not find `langgraph_runtime_inmem` sources —
  [langgraph#8298 comment](https://github.com/langchain-ai/langgraph/issues/8298)). **verified**
- **Durability gap:** [#8298](https://github.com/langchain-ai/langgraph/issues/8298) (closed "completed" 2026-09-25)
  reported that `langgraph dev` checkpoints were only written on clean shutdown — "any SIGKILL/crash/power loss
  silently loses everything since the last graceful exit" — because the 10 s pickle flush loop dropped empty stores.
  Open SWE's desktop app works around this by plugging an `AsyncSqliteSaver` into the dev server via
  `langgraph.json → "checkpointer": {"path": "openswe.local_checkpointer.create_checkpointer"}`; its docstring:
  "The dev server keeps checkpoints in memory and pickles them every ten seconds, so quitting the app loses recent
  thread history" ([`openswe/local_checkpointer.py#L1-L7`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/local_checkpointer.py#L1-L7),
  [`langgraph.desktop.json`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/langgraph.desktop.json)). **verified**
  Even then the run/thread *registry* stays in the in-memory runtime's pickles (inferred from #8298's description of
  `.langgraph_ops.pckl`).
- Docs list a LangSmith API key as a prerequisite for `langgraph dev`; Studio's UI is served from smith.langchain.com
  and talks to the local server from your browser ([FAQ: "Can I use Studio without logging in to LangSmith?"](https://docs.langchain.com/langsmith/faq)). **verified**
- **Verdict (inferred):** great for *debugging the graph in Studio*, not a crash-safe runtime for an unattended workflow.

### 3.3 Option R3 — Agent Server via `langgraph up` / `langgraph build` (standalone, self-hosted)

**What the image contains (verified):** `langgraph build`/`dockerfile` generate `FROM langchain/langgraph-api:<ver>-py3.x[-wolfi]`,
install your package with `uv pip install -c /api/constraints.txt`, and set `LANGSERVE_GRAPHS`, `LANGGRAPH_HTTP`,
`LANGGRAPH_CHECKPOINTER` env vars ([`libs/cli/langgraph_cli/config.py#L1184-L1233`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/cli/langgraph_cli/config.py#L1184-L1233),
[`#L1640-L1647`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/cli/langgraph_cli/config.py#L1640-L1647));
Open SWE's production [`Dockerfile`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/Dockerfile)
is exactly this shape (`FROM langchain/langgraph-api:0.15.1-py3.14`). Base image on Docker Hub: multi-arch
amd64+arm64, ~220–255 MB compressed, 2.2 M pulls, updated 2026-10-12 (Docker Hub API). `image_distro: "wolfi"` is
recommended ([CLI reference](https://docs.langchain.com/langsmith/cli)). The server bundles uvicorn/starlette, an
OpenTelemetry exporter and a Prometheus client (`langgraph-api` 0.16.0 `requires_dist`, PyPI). **verified**

**Backing services (verified):** `REDIS_URI` (pub/sub for streaming, cancellation signalling; "stores only ephemeral
data") and `DATABASE_URI` (Postgres: assistants, threads, runs, crons, checkpoints, store, and the task queue "with
'exactly once' semantics") ([Self-host standalone servers](https://docs.langchain.com/langsmith/deploy-standalone-server),
[Agent Server](https://docs.langchain.com/langsmith/agent-server)). `langgraph up` composes `redis:6`,
`pgvector/pgvector:pg16` and the API container with healthcheck `python /api/healthcheck.py`
([`libs/cli/langgraph_cli/docker.py#L220-L292`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/cli/langgraph_cli/docker.py#L220-L292)).
"Do not run standalone servers in serverless environments. Scale-to-zero may cause task loss." Docker/Compose
examples are labelled "for local development and testing. For production, use the Kubernetes deployment"; non-K8s
deployments must implement "graceful run draining" themselves.

**Runs, crons, cancellation, restart (verified):**
- Background runs: `client.runs.create(thread_id, assistant_id, input=…)`; one run per thread at a time; workers run
  up to `N_JOBS_PER_WORKER` (default 10) concurrently ([Agent Server](https://docs.langchain.com/langsmith/agent-server)).
- Crons: `client.crons.create(...)` / `create_for_thread(...)`, UTC ([Use cron jobs](https://docs.langchain.com/langsmith/cron-jobs)).
- Cancel: `client.runs.cancel(thread_id, run_id, action="interrupt"|"rollback", wait=True)`; `interrupt` keeps the run
  record and checkpoints (resumable); `rollback` deletes them; bulk `cancel_many` ([How to cancel a run](https://docs.langchain.com/langsmith/cancel-run)).
- Restart: `BG_JOB_MAX_RETRIES` (default 3) — on "transient database errors, server shutdown cancellations" the run "is
  placed back in the queue and resumed from the last checkpointed step"; `BG_JOB_SHUTDOWN_GRACE_PERIOD_SECS` default 180
  (max 3600); `BG_JOB_TIMEOUT_SECS` default 86400 ([env vars](https://docs.langchain.com/langsmith/env-var-self-hosted)).
- Checkpoint TTL in `langgraph.json` (`"checkpointer": {"ttl": {"strategy": "delete", "default_ttl": 43200, "sweep_interval_minutes": 60}}`),
  as Open SWE uses ([`langgraph.json`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/langgraph.json)).
- Auth: Open SWE notes "The standalone image defaults to `noop`, which leaves the LangGraph API … open to anyone who can
  reach the port" ([INSTALLATION.md](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/docs/INSTALLATION.md)) → bind to localhost / a private network only.

**Licensing in 2026 (verified, but partly contradictory sources):**
- Standalone server env: `LANGSMITH_API_KEY` and `LANGGRAPH_CLOUD_LICENSE_KEY` ("used to authenticate ONCE at server
  start up") plus egress to `https://beacon.langchain.com` "required for license verification and usage reporting if not
  running in air-gapped mode" ([standalone docs](https://docs.langchain.com/langsmith/deploy-standalone-server)).
- CLI: `langgraph up` "Requires Docker running; LangSmith API key for local dev; license for production"
  ([CLI](https://docs.langchain.com/langsmith/cli)).
- LangChain staff (wfh, forum, 2025-12-19): "Full self-hosting of production workloads currently requires an enterprise
  license"; an API key works "for lighter workloads … That's how `langgraph up` works"
  ([forum](https://forum.langchain.com/t/question-about-the-license/2242)).
- "Self-Hosted Lite" (free ≤1 M nodes) "is now deprecated from a support perspective" (LangChain contributor,
  2025-09-11, [docs#471](https://github.com/langchain-ai/docs/issues/471)).
- Pricing page (published 2026-10-09): Developer $0 (1 seat, 5k traces/mo), Plus $39/seat (1 free *cloud* serverless
  deployment), Enterprise = "Self-hosted and hybrid deployment options" ([langchain.com/pricing](https://www.langchain.com/pricing)).
  The deployment FAQ table still says "Free self-hosted" ([FAQ](https://docs.langchain.com/langsmith/faq)) — stale.
- Server tracing: `LANGSMITH_TRACING` **defaults to `true`** on the Agent Server
  ([env vars](https://docs.langchain.com/langsmith/env-var-self-hosted)) → must be set `false` explicitly.
- **Verdict (inferred):** for our use the Agent Server means a LangSmith account dependency, a phone-home, Postgres +
  Redis, and a production licence we do not have. Not the prototype path.

### 3.4 Option R4 — Aegra (open-source Agent Protocol server)

[aegra/aegra](https://github.com/aegra/aegra): Apache-2.0, 1.26k stars, v0.10.8 (2026-10-01), pushed 2026-10-08,
152 open issues — **maintained but young**. "Drop-in" for the LangGraph SDK (`langgraph_sdk.get_client`), FastAPI +
Postgres (+ Redis for production). From its docs (**verified**, [worker architecture](https://docs.aegra.dev/guides/worker-architecture)):
leases of 30 s renewed by 10 s heartbeats; "When a worker crashes … the lease expires. The reaper resets the run to
`pending` and re-enqueues it. The new worker resumes from the last checkpoint"; `BG_JOB_MAX_RETRIES` 3;
`WORKER_DRAIN_TIMEOUT` 30 s on restart; cross-instance cancel via Redis pub/sub; crons with lease-claimed
at-least-once firing ([cron](https://docs.aegra.dev/guides/cron)); tracing to "any OTLP backend (Langfuse, Phoenix, etc.)".
`aegra-api` 0.10.8 depends on `langgraph-checkpoint-postgres>=3.1.1`, `redis[hiredis]` (PyPI). **verified**
Fit (inferred): the closest thing to "Agent Server API without a licence" for stage (b) if we want an HTTP control
plane (`threads.search`, `runs.cancel`, crons) instead of writing our own CLI. Risk: young project; validate
crash-recovery claims ourselves before relying on them.

### 3.5 "Canned workflow container" architectures (graph + coding CLI + its own auth)

1. **Open SWE** (langchain-ai/open-swe, MIT): one Agent Server image (`langgraph.json` declares graphs `agent`,
   `reviewer`, `review-scout`, `chat`, `scheduler`; FastAPI app for webhooks + dashboard) + Postgres + Redis;
   coding happens in **separate per-thread sandboxes** (LangSmith sandboxes by default; Daytona, Runloop, E2B, Modal, or
   `local` = "no isolation — development only"). GitHub credentials are injected by the sandbox **egress proxy** ("The proxy
   token is minted at runtime from the GitHub App installation credentials"), not stored in the sandbox
   ([CUSTOMIZATION.md §1](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/docs/CUSTOMIZATION.md)).
   The sandbox id lives in thread metadata and is reconnected on resume; "An unreachable existing sandbox must raise
   rather than be replaced, because replacement would lose the thread's work"
   ([`openswe/sandboxes/AGENTS.md`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/sandboxes/AGENTS.md),
   [`state.py#L147-L165`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/sandboxes/state.py#L147-L165)).
   Production standalone deployments "require a license key" (README). Its desktop app instead bundles `langgraph dev`
   + SQLite and supervises it from Electron (`desktop/src/backend-supervisor.cjs`). **verified**
   Difference from our rule: Open SWE's sandbox *can* push (via proxy); ours must not.
2. **`openai/codex-universal`** (MIT per `LICENSES/LICENSE`, 1.1k stars, last push 2026-05-02): "a reference
   implementation of the base Docker image available in OpenAI Codex" — Ubuntu 24.04 with many toolchains selectable by
   `CODEX_ENV_*`; built for amd64+arm64 but "we only run the linux/amd64 version"; it does **not** install the Codex CLI
   itself ([README](https://github.com/openai/codex-universal), [Dockerfile](https://github.com/openai/codex-universal/blob/main/Dockerfile)). **verified**
   Use as a *sandbox* base image (S3/S4 run inside it), not as the workflow image.
3. **Codex CLI with its own ChatGPT login inside a container** ([Codex auth](https://learn.chatgpt.com/docs/auth),
   [Maintain Codex account auth in CI/CD](https://learn.chatgpt.com/docs/auth/ci-cd-auth), fetched 2026-10-13): credentials are
   cached "in a plaintext file at `~/.codex/auth.json` or in your OS-specific credential store"; set
   `cli_auth_credentials_store = "file"`; `codex login --device-auth` for headless login; Codex refreshes tokens itself
   ("if `last_refresh` is older than about 8 days, Codex refreshes the token bundle") and writes them back, so the
   container must keep a **persistent `CODEX_HOME` volume** and "seed `auth.json` only if it is missing"; "only one
   machine or serialized job stream will use a given `auth.json` copy"; "The right way to authenticate automation is
   with an API key." **verified**
4. **`openai/codex-action`** (Apache-2.0, 1.27k stars): runs Codex in CI with an API key behind a local **Responses API
   proxy** and a `safety-strategy` (`drop-sudo` / `unprivileged-user` / `read-only`) because "read-only access to the
   filesystem and `sudo` can be used to expose your `OPENAI_API_KEY`"
   ([README](https://github.com/openai/codex-action), [docs/security.md](https://github.com/openai/codex-action/blob/main/docs/security.md)). **verified**
   → secret-isolation pattern: the agent process uses a credential through a proxy it cannot read.

**Proposed canned container for us (inferred):**

```
image: oc2-workflow  (python:3.12-slim or wolfi; non-root uid)
  /app            graph code (langgraph, langgraph-checkpoint-sqlite|postgres, httpx/PyGithub), no LLM in deterministic nodes
  codex CLI       pinned version; CODEX_HOME=/state/codex (volume; auth.json seeded once, refreshed in place)
  /state          volume: checkpoints.sqlite (WAL), runs ledger, logs
  entrypoint      wf serve | wf tick | wf run --issue N | wf status | wf resume THREAD --answer ... | wf cancel THREAD
sandbox:          builder/reviewer run `codex exec` in a *separate* container per task (codex-universal-like image),
                  with the worktree bind-mounted and NO GitHub token; the workflow container holds the GitHub App key
                  and does push/PR/CI calls itself (S5/S6/S9).
```
Where the Codex process itself runs (workflow container, sandbox container, or behind a token proxy) is open — see
§7 question 2; each option trades the ChatGPT token's exposure against the GitHub credentials' exposure.

### 3.6 More examples of "own runtime on the LangGraph library" (R1 in the wild)

- **DeerFlow** (bytedance/deer-flow, MIT, 83.8k stars, pushed 2026-10-13): production image runs its own FastAPI
  gateway (`uvicorn app.gateway.app:app`, [`backend/Dockerfile`](https://github.com/bytedance/deer-flow/blob/6783073a39f2de19b11d952d87f55e3fa67601f9/backend/Dockerfile)),
  with a configurable checkpointer `memory | sqlite | postgres`
  ([`checkpointer_config.py`](https://github.com/bytedance/deer-flow/blob/6783073a39f2de19b11d952d87f55e3fa67601f9/backend/packages/harness/deerflow/config/checkpointer_config.py)),
  an in-process `langgraph_runtime` with run drain on shutdown, `/health` (liveness) and `/health/ready` (probes the
  checkpointer/store) ([`app/gateway/AGENTS.md`](https://github.com/bytedance/deer-flow/blob/6783073a39f2de19b11d952d87f55e3fa67601f9/backend/app/gateway/AGENTS.md)).
  `langgraph.json` is kept for Studio with a custom `checkpointer.path`. Its draft
  [checkpoint retention contract](https://github.com/bytedance/deer-flow/blob/6783073a39f2de19b11d952d87f55e3fa67601f9/backend/docs/checkpoint-retention-contract.md)
  warns that deleting checkpoints by age breaks parent chains and that pending-write rows "are uncommitted/in-flight
  state, not garbage" — relevant when we add retention. **verified**
- **Open SWE desktop**: bundled `langgraph dev` + custom SQLite checkpointer, supervised by Electron
  (`uv run langgraph dev --no-browser --no-reload --host 127.0.0.1 --n-jobs-per-worker 10 --config langgraph.desktop.json`,
  health = poll `GET /` until 200 within 60 s, stop = SIGTERM then SIGKILL after 5 s)
  ([`desktop/src/backend-supervisor.cjs`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/desktop/src/backend-supervisor.cjs)). **verified**
  It also implements "Sign in with ChatGPT" itself (PKCE on localhost 1455/1457, calls `https://chatgpt.com/backend-api/codex`
  with the Codex CLI's public OAuth client id) — [`desktop/src/openai-oauth.cts`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/desktop/src/openai-oauth.cts). **verified**;
  whether reusing Codex's client id is within OpenAI's terms is **not verified** — do not copy without checking.

---

## 4. Supervision: health, stuck runs, restart, external control

### 4.1 What exists out of the box

| Concern | Plain LangGraph library (R1) | Agent Server (R3) / Aegra (R4) |
|---|---|---|
| Health | none — you write it (e.g. `wf health` = DB opens + ledger readable + last tick < N min) | `GET /ok` → `{"ok":true}` ([standalone docs](https://docs.langchain.com/langsmith/deploy-standalone-server)); Prometheus `GET /metrics` with `lg_api_num_pending_runs`, `lg_api_num_running_runs`, `lg_api_workers_available`, `lg_api_run_failed_after_retry_counter`, `lg_api_run_abandoned_by_shutdown_counter` ([metrics](https://docs.langchain.com/langsmith/self-hosted-agent-server-metrics)) **verified** |
| List runs | your ledger; `graph.get_state(config)` per thread (`next`, `tasks[].interrupts`, `tasks[].error`, `created_at`); `checkpointer.list(None)` iterates all checkpoints (Open SWE does `InMemorySaver().alist(None)` to copy everything — [`local_checkpointer.py`](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/local_checkpointer.py)) **verified** | `threads.search(status=…, metadata=…)` with status `idle` / `busy` / `interrupted` / `error`, `runs.list(thread_id)` ([use-threads](https://docs.langchain.com/langsmith/use-threads)) **verified** |
| Resume | `invoke(None, cfg)` / `invoke(Command(resume=x), cfg)` | `POST /threads/{id}/runs/wait {"assistant_id":…, "command":{"resume":…}}` ([HITL via API](https://docs.langchain.com/langsmith/add-human-in-the-loop)) **verified** |
| Cancel | `RunControl.request_drain()` (cooperative, between super-steps); kill the process for a hard stop (resume later from the last checkpoint) **verified** | `runs.cancel(…, action="interrupt"\|"rollback")`, `cancel_many` **verified** |
| Stuck node | `TimeoutPolicy(run_timeout, idle_timeout, refresh_on="heartbeat")` → `NodeTimeoutError` → `error_handler` → S10 **verified** | same (it is the library), plus `BG_JOB_TIMEOUT_SECS` per run **verified** |
| Restart | launchd `KeepAlive` / Docker `restart: unless-stopped` / systemd; on start, resume non-terminal threads **inferred** | built in: requeue + resume from last checkpoint, `BG_JOB_MAX_RETRIES`=3, shutdown grace 180 s (Agent Server); lease reaper (Aegra) **verified** |
| Loop/budget limits | explicit counters in state (`build_attempts`, `ci_attempts`, `review_round`) + `recursion_limit` (default 1000) + token budget via `langchain_core.callbacks.get_usage_metadata_callback()` ([source](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/callbacks/usage.py)) **verified API / inferred use** | same |

### 4.2 Stuck-run detection design (inferred)

Three layers, cheapest first:
1. **In-node**: every agent node (S3, S7) gets `timeout=TimeoutPolicy(run_timeout=…, idle_timeout=…)`. The builder
   wrapper calls `runtime.heartbeat()` whenever the coding CLI emits an event (e.g. each JSONL line of `codex exec --json`),
   so "no output for 10 min" = stuck. Deterministic nodes get short `run_timeout`s.
2. **Graph-level budgets**: per-issue wall-clock deadline and token/cost budget stored in state at intake; every node
   checks them on entry; breach → `Command(goto="blocked")`.
3. **External watchdog** (the supervisor): for each thread in the ledger whose status is `running`, compare the latest
   checkpoint's `created_at` (from `get_state`) and the runner's heartbeat file with `now`; if older than the node's
   `run_timeout` + margin, the worker is wedged (e.g. a blocking call ignoring asyncio cancellation) → restart the
   worker process; the thread resumes from its last checkpoint. Escalate after N restarts.

Prior art for 3: Aegra's 30 s lease + 10 s heartbeat + reaper (§3.4) and the Agent Server's
`lg_api_run_abandoned_by_shutdown_counter`/retry metrics. Open SWE uses TTL'd "lock threads" and per-PR dispatch
fingerprints to avoid duplicate work (§2.3). **verified (prior art)**

### 4.3 How an external supervisor (later: OpenClaw cron command jobs) would drive it

Context from this repo (read-only): the backlog-autonomy design already runs "an OpenClaw cron job with a command
payload" that does `docker run --rm <ops image> ops.backlog_poll` every 10 minutes with no model
([`docs/design/backlog-autonomy/README.md` §3–4](https://github.com/bodegus/openclaw2-deploy/blob/5f893376dde7da354f428232e3855e75042799fd/docs/design/backlog-autonomy/README.md)). The same shape fits here (**inferred**):

- **Contract = a small CLI with JSON output** in the workflow image, independent of whether the backend is the
  library (R1) or an Agent Protocol server (R4):
  - `wf status [--json]` → per thread: issue, node (`next`), status (`running|waiting_ci|waiting_human|blocked|merge_ready|failed`),
    loop counters, last progress time, PR URL.
  - `wf tick` → start new eligible issues (WIP limit), resume finished CI waits, resume threads whose human answered,
    restart wedged ones, exit 0/!0. Idempotent; guarded by a lock file.
  - `wf resume <thread> --answer …`, `wf cancel <thread> [--reason]`, `wf health`.
- OpenClaw's cron job runs `docker exec oc2-workflow wf tick` (long-lived container) or
  `docker run --rm -v wf-state:/state oc2-workflow wf tick` (one-shot), and reads `wf status --json` for
  Telegram/Todoist reporting. No HTTP server is needed for that; if we adopt Aegra later, the CLI simply calls its
  REST API instead of the library.
- Restart policy on Linux rootless Docker: `restart: unless-stopped` for a long-lived worker container; the rootless
  daemon itself runs as a `systemctl --user` service and needs `loginctl enable-linger <user>` to start at boot
  ([Docker rootless docs](https://docs.docker.com/engine/security/rootless/)). **verified**
- Graceful stop: `docker stop --time 120` → SIGTERM → `RunControl.request_drain()` → `GraphDrained` at the next
  super-step; note a long S3 node "runs to completion" before the drain takes effect, so the stop timeout must either
  exceed the builder's worst case or accept a SIGKILL + resume-from-last-checkpoint (which re-runs the builder node).
  **verified semantics / inferred tuning**

---

## 5. Observability without third-party egress by default

### 5.1 Egress inventory and switches (verified)

| Component | Default egress | Switch |
|---|---|---|
| `langsmith` SDK (used by LangChain/LangGraph callbacks) | **off** unless `LANGSMITH_TRACING`/`LANGCHAIN_TRACING`(`_V2`) == `"true"` — [`langsmith/utils.py tracing_is_enabled`](https://github.com/langchain-ai/langsmith-sdk/blob/a155e95489c536c84ebdb02cc1490111b13221c4/python/langsmith/utils.py#L121-L142), env lookup in both `LANGSMITH_*` and `LANGCHAIN_*` namespaces ([`#L420-L437`](https://github.com/langchain-ai/langsmith-sdk/blob/a155e95489c536c84ebdb02cc1490111b13221c4/python/langsmith/utils.py#L420-L437)) | set `LANGSMITH_TRACING=false` explicitly anyway; do not set `LANGSMITH_API_KEY` in the workflow env |
| Agent Server (`langgraph-api`) | `LANGSMITH_TRACING` **defaults to `true`** ([env vars](https://docs.langchain.com/langsmith/env-var-self-hosted)); licence/usage beacon to `beacon.langchain.com` ([standalone](https://docs.langchain.com/langsmith/deploy-standalone-server)) | `LANGSMITH_TRACING=false`; beacon cannot be disabled except with an air-gapped licence ([egress](https://docs.langchain.com/langsmith/self-host-egress)) |
| `langgraph` CLI | anonymised command analytics (OS, Python/CLI version, command, flag booleans) POSTed to a Supabase endpoint in a background thread ([`analytics.py#L86-L104`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/cli/langgraph_cli/analytics.py#L86-L104), [`constants.py`](https://github.com/langchain-ai/langgraph/blob/afbe7e48b17f62e139b5c6337ab934549e6dc73b/libs/cli/langgraph_cli/constants.py)) | `LANGGRAPH_CLI_NO_ANALYTICS=1` |
| LangSmith Studio | UI is served from smith.langchain.com and needs a LangSmith account/API key; "With tracing disabled, no data leaves your local server" ([Studio](https://docs.langchain.com/oss/python/langgraph/studio)) | `LANGSMITH_TRACING=false`; use only for local debugging |
| Codex CLI | `otel.metrics_exporter` "defaults to `statsig`"; `analytics.enabled` "When unset, the client default applies" ([Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)) | in the container's `config.toml`: `analytics.enabled = false`, `otel.metrics_exporter = "none"` (or `otlp-http` to our collector); `otel.log_user_prompt` stays off |
| Langfuse self-hosted | usage stats to PostHog by default ("does not include raw traces, prompts …") ([README](https://github.com/langfuse/langfuse/blob/be91bdbfd6a8d06bc2354955cc0f5cf0120fe24e/README.md); compose default `TELEMETRY_ENABLED: ${TELEMETRY_ENABLED:-true}` [`docker-compose.yml#L26`](https://github.com/langfuse/langfuse/blob/be91bdbfd6a8d06bc2354955cc0f5cf0120fe24e/docker-compose.yml#L26)) | `TELEMETRY_ENABLED=false` |
| Arize Phoenix self-hosted | UI analytics on by default | `PHOENIX_TELEMETRY_ENABLED=false` ([config](https://arize.com/docs/phoenix/self-hosting/configuration)) |

### 5.2 Options, lightest first

1. **No extra service: LangGraph's own data.** The checkpointer *is* an audit log: `get_state_history(config)` gives every
   super-step with `metadata.writes`, `created_at`, task errors and interrupts ([checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)).
   Stream modes `updates`, `tasks` ("Task start/finish events with results and errors"), `checkpoints`, `debug`
   ([streaming](https://docs.langchain.com/oss/python/langgraph/streaming)); v1.2 adds typed "event streaming"
   (`graph.stream_events(..., version="v3")`, [event-streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)).
   → write one JSONL event file per thread (`/state/logs/<thread>.jsonl`) + `structlog` JSON logs; the Codex CLI's own
   `codex exec --json` transcript goes next to it. Zero egress, enough for `wf status` and post-mortems. **verified APIs / inferred design**
2. **OpenTelemetry to a local collector/backend.** LangChain/LangGraph spans via `LANGSMITH_OTEL_ENABLED=true`,
   `LANGSMITH_TRACING=true`, `LANGSMITH_OTEL_ONLY="true"` ("To send traces **only** to your OTEL endpoint"), and
   `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318`; note "if unset, your LangSmith API key and project are sent" as
   OTLP headers, so keep the key out of the env ([Trace with OpenTelemetry](https://docs.langchain.com/langsmith/trace-with-opentelemetry),
   langsmith ≥ 0.4.25 recommended; we saw 0.14.8). Alternative instrumentation: OpenInference
   `openinference-instrumentation-langchain` 0.1.79 (Apache-2.0, [Arize-ai/openinference](https://github.com/Arize-ai/openinference), 1.26k stars). **verified**
   Backends: Jaeger (Apache-2.0, 23.3k stars) for plain traces; **Arize Phoenix** (single container, SQLite in
   `PHOENIX_WORKING_DIR` or Postgres, UI+OTLP on 6006, gRPC 4317; Elastic-2.0; 11.8k stars) for LLM-aware views. **verified**
   The Agent Server can also export its own APM spans with `LS_APM_OTEL_ENABLED=true` + `OTEL_EXPORTER_OTLP_ENDPOINT`
   ([env vars](https://docs.langchain.com/langsmith/env-var-self-hosted)). Aegra advertises "Fan-out tracing … Langfuse,
   Phoenix, or any OTLP backend". **verified**
3. **Self-hosted Langfuse** (v4.58.0, 2026-10-13; MIT core + `ee/` licence-key features; 35.7k stars). Compose stack =
   `langfuse-web`, `langfuse-worker`, Postgres 17, ClickHouse 25.12, Redis 7, MinIO
   ([`docker-compose.yml`](https://github.com/langfuse/langfuse/blob/be91bdbfd6a8d06bc2354955cc0f5cf0120fe24e/docker-compose.yml)).
   Ingest via the Langfuse SDK's LangChain `CallbackHandler` (recommended by Langfuse over raw OTel) or OTLP at
   `/api/public/otel` (HTTP/JSON or HTTP/protobuf, no gRPC; Basic auth `pk:sk`) ([Langfuse OTel](https://langfuse.com/integrations/native/opentelemetry)). **verified**
   Heavy for a Mac prototype (6 containers incl. ClickHouse); reasonable on the Linux host if we want trace UIs, evals,
   cost dashboards.
4. **LangSmith (cloud)** — best LangGraph-native UI, but sends prompts/code to a third party; keep off by default; if
   ever used, the SDK supports masking/anonymizers ([redact secrets](https://docs.langchain.com/langsmith/redact-secrets)). **verified (exists)**

### 5.3 Recommendation (inferred)
- Mac prototype: option 1 (JSONL + checkpoint history) and optionally Phoenix in one container for span views;
  `LANGSMITH_TRACING=false`, `LANGGRAPH_CLI_NO_ANALYTICS=1`, Codex `analytics.enabled=false`, `otel.metrics_exporter="none"`.
- Linux host: an OTel Collector container on the same Docker network, exporting to Phoenix (one container) or a
  self-hosted Langfuse; never LangSmith by default. Note: this repo's research says the home-infra `observability`
  role ships Telegraf/Logstash → **MongoDB Atlas** + Grafana and that whether it still runs on the host is unchecked
  ([`docs/design/backlog-autonomy/research.md` L131, L647](https://github.com/bodegus/openclaw2-deploy/blob/5f893376dde7da354f428232e3855e75042799fd/docs/design/backlog-autonomy/research.md)) —
  Atlas is itself third-party egress, so agent traces (prompts, diffs) should not go there by default.

---

## 6. Recommendation (inferred unless marked)

### 6.1 (a) Mac prototype — "plain library + SQLite + launchd", no LangChain services

| Area | Choice | Why / evidence |
|---|---|---|
| Runtime | One Python 3.12/3.13 package `oc2wf`, `langgraph>=1.2.15,<1.3`, `langgraph-checkpoint-sqlite>=3.1.2` (`AsyncSqliteSaver`), async nodes, `ainvoke/astream` | MIT only; 1.2 brings node timeouts, error handlers, `RunControl` drain (§1.5); timeouts need async nodes |
| Durability | `durability="sync"` on every call; WAL SQLite at `~/.oc2wf/state/checkpoints.sqlite` | few, slow super-steps; default is `"async"` (§1.2) |
| Thread id | `gh:{owner}/{repo}#{issue}` (+ `/r{n}` only for a deliberate fresh restart) | deterministic → "start" is idempotent; < 255 chars keeps the Postgres option open |
| Ledger | `runs` table in the same DB, written **before** the first `ainvoke`: issue, thread_id, status, timestamps, `codex_session_id`, `pr_number`, `head_sha`, `flow_version` | covers crash-before-first-checkpoint (#8764) and gives `status` a cheap index |
| State | small, JSON-only: ids, SHAs, counters (`build_attempt`, `ci_attempt`, `review_round`), deadlines, budgets, verdict JSON, ≤ few KB log excerpts; big things (CI logs, diffs, transcripts) as files under `~/.oc2wf/state/artifacts/<thread>/` referenced by path | checkpoints store every channel every super-step (§1.1); keep them small |
| Node policies | `set_node_defaults(retry_policy=RetryPolicy(max_attempts=3, retry_on=<transient HTTP>), error_handler=<route to blocked>)`; S3/S7 `TimeoutPolicy(run_timeout≈60 min, idle_timeout≈10 min, refresh_on="heartbeat")`; S6 `run_timeout≈90 min` | built-in stuck detection + failure routing (§1.5) |
| Side effects | check-before-act in S2/S5/S9 (§1.4 table), GitHub calls wrapped in `@task` inside the publish node, hidden-marker comments | nodes re-run after crashes; #8039 means even `sync` is not exactly-once |
| Waits | S6: poll inside the node (30–60 s) with heartbeats. S10: `interrupt({...})` and exit; answer via CLI | §2.4 |
| Agent loops | `codex exec --json` in a per-task Docker container (worktree bind-mounted, no GitHub token); session id → ledger on `thread.started`; resume with `codex exec resume <id>`. Mounting `CODEX_HOME` into that container exposes the ChatGPT token to repo code — decide via open question 2 | §1.8 |
| LLM auth | separate Codex login for the workflow: `CODEX_HOME=~/.oc2wf/codex`, `cli_auth_credentials_store="file"`, `codex login` once; one serialized consumer per `auth.json` copy | §3.5 item 3 (verified docs) |
| GitHub creds | only in the host `oc2wf` process (fine-grained PAT or GitHub App key in macOS Keychain/env), used by deterministic nodes S1/S5/S6/S9 | requirement; Open SWE's proxy approach is the alternative |
| Process | `oc2wf serve` under a LaunchAgent: `KeepAlive={SuccessfulExit=false}`, `ThrottleInterval=30`, `ExitTimeOut=120`; SIGTERM → `RunControl.request_drain()` for each active run; on start, resume every ledger row in `running` state with `ainvoke(None, cfg)` | `man launchd.plist`; §1.5 |
| CLI | `oc2wf start <issue-url>`, `status [--json]`, `answer <thread> "<text>"`, `resume <thread>`, `cancel <thread>`, `health` | the same contract OpenClaw will call later (§4.3) |
| Observability | per-thread JSONL (stream mode `updates`+`tasks`) + `get_state_history`; `LANGSMITH_TRACING=false`, `LANGGRAPH_CLI_NO_ANALYTICS=1`, Codex `analytics.enabled=false`, `otel.metrics_exporter="none"`; optional Phoenix container for spans | §5 |
| Debug UI | `langgraph dev` + Studio only while developing (needs a LangSmith account; keep tracing off); never as the runtime | §3.2 |
| Proof (done-when) | crash-injection test: SIGKILL the worker at the start of each node and mid-S3/S6, restart, assert exactly one branch push, one PR, one summary comment, and that the run reaches merge-ready | the only way to trust §1.2/#8039 on our versions |

### 6.2 (b) Later, next to OpenClaw on Linux with rootless Docker

- **Same code, one image** `oc2-workflow` (python:3.12-slim or Wolfi base, non-root UID), pinned `langgraph`,
  checkpointer, Codex CLI; named volume `/state` (SQLite DB, artifacts, `CODEX_HOME`). Compose service with
  `restart: unless-stopped`, `stop_grace_period` ≥ the worst-case node you are willing to wait for (or accept SIGKILL +
  resume), healthcheck `oc2wf health`. Rootless daemon as a `systemctl --user` service with `loginctl enable-linger`.
- **Supervisor = OpenClaw cron command job** (the pattern this repo already uses for `ops.backlog_poll`): every 5–10
  min run `oc2wf tick --json` (start eligible issues within a WIP limit, resume finished waits, restart wedged runs,
  report) and post `oc2wf status --json` deltas to Telegram/Todoist. If the cron job can only start one-shot containers,
  have the long-lived worker expose the same CLI over a Unix socket or small localhost HTTP endpoint on the shared
  volume/network (open question 6).
- **Checkpointer:** stay on SQLite while there is one worker process; move to a Postgres container with
  `AsyncPostgresSaver` when adding workers or an Agent Protocol server (§1.3).
- **HTTP control plane (optional):** if we want `threads.search`, run cancellation, crons and run webhooks without
  writing them, evaluate **Aegra** (Apache-2.0; Postgres + Redis) behind the same CLI, after a SIGKILL test of its lease
  recovery. Do **not** plan on the LangGraph Agent Server: production self-hosting needs an Enterprise licence
  (staff statement 2025-12-19), it phones home to `beacon.langchain.com`, tracing defaults on (§3.3).
- **Long waits:** keep in-node CI polling; optionally add a GitHub `check_suite`/`workflow_run` webhook receiver later
  and switch S6 to interrupt-and-resume (§2.3) — the node interface was kept compatible.
- **Sandboxes:** per-task containers for `codex exec` with no GitHub token. Launching them requires Docker API access
  from the worker; with rootless Docker that is the service user's whole Docker authority — prefer reusing OpenClaw's
  sandbox mechanism or a narrow launcher (open question 3).
- **Observability:** OTel Collector → Phoenix or self-hosted Langfuse on the host (telemetry flags off); no LangSmith;
  do not route prompts/diffs to the MongoDB Atlas-backed stack by default.

---

## 7. Open questions

1. **Concurrent Codex processes on one ChatGPT `auth.json`.** Docs: "only one machine or serialized job stream will
   use a given `auth.json` copy". Can a builder and a reviewer run in parallel with one login, or must Codex calls be
   serialized (or use two logins)? Needs a test.
2. **Where Codex runs.** (i) In the workflow container: the ChatGPT token stays out of the repo container, but the
   commands Codex executes would run next to the GitHub credentials unless Codex's own sandbox (`--sandbox
   workspace-write` / permission profiles) is trusted to hide them. (ii) In the per-task sandbox container: no GitHub
   credentials there, but the ChatGPT token in `CODEX_HOME` is readable by repository code (Codex's docs warn against
   exposing API keys to jobs that run repository-controlled code). (iii) A token-holding proxy in front of the model
   API, as `openai/codex-action` does for API keys — unknown whether this works with ChatGPT OAuth.
3. **Sandbox launching on the Linux host** without giving the worker the rootless Docker socket — reuse OpenClaw's
   sandbox, or a narrow launcher service?
4. **LangGraph #8039** (completed node can re-execute after SIGKILL even under `sync`) — does it reproduce with
   `langgraph` 1.2.15 + `AsyncSqliteSaver`? Our idempotency design assumes yes; the crash-injection test will tell.
5. **Agent Server licensing** — sources conflict (FAQ "Free self-hosted" vs pricing page "Enterprise"); only matters if
   we ever want it; would need a written answer from LangChain.
6. **OpenClaw cron command jobs**: can they `docker exec` into a long-lived container, or only `docker run --rm` one-shot
   containers on a shared volume? This decides whether the worker is long-lived (in-node CI polling) or tick-based.
7. **Studio** requires a LangSmith account even with tracing off — acceptable for local debugging only?
8. **Checkpoint retention**: when to `delete_thread` (after merge-ready + N days?) without breaking the audit trail;
   DeerFlow's draft contract is a useful template.
