# 03 — Deterministic steps and routing (S1, S2, S4, S5, S6, S8, S9, S10)

Research date: 2026-10-13. Status: COMPLETE (sections 1-9).

Legend: **verified** = read in a primary source (link given; version/date noted); **inferred** = my reasoning
or an unconfirmed secondary source.

Pinned versions seen today:
- LangGraph (Python) **1.2.15**, released 2026-10-12 (tag commit `08a3456`), repo langchain-ai/langgraph:
  43.2k stars, MIT, pushed 2026-10-13, maintained. Also released 2026-10-12: `checkpoint==4.3.0`,
  `checkpointsqlite==3.1.2`, `checkpointpostgres==3.1.3`, `sdk==0.4.7`. **verified**
  (`gh api repos/langchain-ai/langgraph/releases`, 2026-10-13).

Sibling files: durability/supervision details are in `04-durability-and-packaging.md`; builder/reviewer
loops in `02-builder-reviewer-harness.md`. This file covers only the plain-code steps and the routing.

## Contents
1. Graph mechanics (LangGraph 1.2.x)
2. GitHub access for S1 / S5 / S9 (library, auth, token isolation)
3. S2 git and workspace (git library, worktree vs clone, container per task)
4. S4 local gate
5. S6 CI wait without an LLM
6. S8 review-fix loop control
7. S10 human-in-the-loop
8. Graph sketch (state schema, nodes, edges, routers)
9. Recommendations summary and open questions

---
## 1. Graph mechanics (LangGraph 1.2.15)

Permalink base used below: `LG = https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph`
(tag `1.2.15`). Docs pages are the live `docs.langchain.com/oss/python/langgraph/*` pages read 2026-10-13.

### 1.1 StateGraph vs Functional API

| | StateGraph (Graph API) | Functional API (`@entrypoint` / `@task`) |
|---|---|---|
| Control flow | explicit nodes + edges + routers | plain Python `if`/`while` |
| Checkpoints | a new checkpoint after every super-step | task results saved into the entrypoint's checkpoint |
| Resume | re-runs the interrupted **node** from its start | **replays the whole entrypoint**; completed tasks are restored from the checkpoint |
| Visualisation | yes (Mermaid/PNG, Studio) | no ("graph is dynamically generated during runtime") |
| Determinism burden | low (graph changes allowed between resumes) | high (do not reorder tasks/interrupts; all side effects must be tasks) |

- **verified**: comparison bullets (control flow, checkpointing, visualisation) — [functional-api.md "Functional API vs. Graph API"](https://docs.langchain.com/oss/python/langgraph/functional-api.md); replay semantics and "place side effects in tasks" — same page, "Determinism" / "Idempotency"; "You can add or remove nodes and edges without breaking resume for existing threads" — [graph-api.md "Re-execution and idempotency"](https://docs.langchain.com/oss/python/langgraph/graph-api.md); choice guidance ("Conditional branching with multiple decision points" → Graph API; "Rapid prototyping" → Functional) — [choosing-apis.md](https://docs.langchain.com/oss/python/langgraph/choosing-apis.md).
- **Mixed use is supported**: a StateGraph node may call `@task` functions; "Task results are checkpointed ... so resuming a thread can skip completed task work inside the node" — **verified**, [graph-api.md "Using tasks in nodes"](https://docs.langchain.com/oss/python/langgraph/graph-api.md).

**Recommendation:** StateGraph for the outer S1–S10 pipeline (the brief asks for a declarative graph; every
route is a named edge that can be drawn, unit-tested and logged). Inside multi-effect nodes (S5 publish: commit →
push → open PR) wrap each external effect in a `@task` so a crash between "push" and "open PR" does not repeat the
push on resume. **inferred** from the two verified facts above.

### 1.2 Typed state, reducers, runtime context
- Default reducer = overwrite; `Annotated[list[T], operator.add]` appends; `Overwrite([])` clears a merging field
  ("returning an empty value does **not** clear the field"). **verified**, [graph-api.md "Reducers" / "Resetting a reducer field"](https://docs.langchain.com/oss/python/langgraph/graph-api.md).
- Dependencies that must not be checkpointed (GitHub client factory, Docker client, token provider) go in
  `context_schema` / `Runtime.context`, passed fresh on every `invoke`. **verified** ([graph-api.md "Runtime context"](https://docs.langchain.com/oss/python/langgraph/graph-api.md)); "never put a token in state" is **inferred** (state is persisted in the checkpoint DB).
- Checkpoint serializer: permissive by default for custom Python types ("all types allowed with a warning");
  `LANGGRAPH_STRICT_MSGPACK=true` restricts deserialisation to a safe allowlist, and the docstring warns that
  write access to the checkpoint DB can lead to code execution. **verified**, [checkpoint/serde/jsonplus.py L104-L136](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/checkpoint/langgraph/checkpoint/serde/jsonplus.py#L104-L136).
  → Keep state JSON-primitive (str/int/bool/list/dict; Pydantic only at node boundaries via `.model_dump()`),
  turn strict mode on, and keep the SQLite file outside every container mount. **inferred**.

### 1.3 Routing: conditional edges vs `Command`
- `add_conditional_edges(src, router, path_map)` — pure function of state → next node name(s). **verified**,
  [graph-api.md "Conditional edges"](https://docs.langchain.com/oss/python/langgraph/graph-api.md).
- `Command(update=..., goto=...)` returned from a node combines a state write and a route; the node must be
  annotated `-> Command[Literal["a","b"]]` for rendering; **static edges still fire** in addition to `goto`, so use
  one or the other per node. **verified**, same page "Command" (Note + Warning blocks); class at
  [LG/types.py L833-L880](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L833-L880).
- `Command(resume=...)` is the **only** Command form to pass as graph input. **verified**, [interrupts.md "Resuming interrupts"](https://docs.langchain.com/oss/python/langgraph/interrupts.md).

**Recommendation:** deterministic work nodes return plain dict updates (facts: `ci_status="red"`, `failing_jobs=[...]`);
routing lives in small pure `route_after_*` functions attached with `add_conditional_edges`. Routers then are
unit-testable without a graph (`assert route_after_ci(state) == "S3_build"`), and the counters/limits are visible in
one place. Use `Command` only in error handlers (1.6), where an update and a jump must be atomic. **inferred**.

### 1.4 Subgraphs for builder (S3) and reviewer (S7)
- Two ways: add the compiled subgraph as a node (shared keys, no wrapper) or **call it inside a node function**
  (different schemas; you map state in/out). **verified**, [use-subgraphs.md](https://docs.langchain.com/oss/python/langgraph/use-subgraphs.md).
- Subgraph checkpointer modes: `None` = per-invocation (default; inherits parent checkpointer, supports interrupts),
  `True` = per-thread (state accumulates across calls on the same thread), `False` = stateless (no interrupts, no
  durable execution). **verified**, same page and [LG/types.py L109-L115](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L109-L115).
- When a subgraph called from a node is resumed, "the parent graph will resume execution from the beginning of the
  node where the subgraph was invoked". **verified**, [interrupts.md "Using with subgraphs called as functions"](https://docs.langchain.com/oss/python/langgraph/interrupts.md).

**Recommendation:** wrap builder/reviewer in `S3_build` / `S7_review` node functions that build a small typed
input (issue, plan, failing log, findings) and copy back only a typed result (`BuildResult`, `ReviewVerdict`).
This keeps the agent's message history out of the parent state and keeps the parent schema stable whatever agent
harness is used (Deep Agents, `create_agent`, or a Codex CLI subprocess). Default (per-invocation) checkpointer
mode, so a crash mid-build resumes the agent loop inside the same S3 attempt. **inferred**.

### 1.5 Bounded loops: counters in state + recursion limit as a backstop
- `recursion_limit` caps super-steps **per invocation**: the loop computes `stop = step + recursion_limit + 1` from
  the checkpoint's step at the start of every run. **verified**, [LG/pregel/_loop.py L1858-L1859](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/pregel/_loop.py#L1858-L1859).
  So each resume after an interrupt gets a fresh budget — it is not a lifetime bound.
- Default: docs say "Starting in version 1.0.6, the default recursion limit is set to 1000 steps"
  ([graph-api.md "Recursion limit"](https://docs.langchain.com/oss/python/langgraph/graph-api.md)), but the 1.2.15 code has
  `DEFAULT_RECURSION_LIMIT = int(getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", "10007"))`
  ([LG/_internal/_config.py L32](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/_internal/_config.py#L32)). **verified** (docs and code disagree; either way far too high to bound our loops).
- `RemainingSteps` managed value lets a router degrade gracefully before `GraphRecursionError`. **verified**, graph-api.md "Proactive recursion handling".

**Recommendation:** explicit counters (`build_attempts`, `local_gate_failures`, `ci_failures`, `review_round`,
`human_asks`) checked in routers, each with a named limit in a `Limits` config; route to `S10_blocked` with a
reason when exceeded. Set `recursion_limit` explicitly (e.g. 150) only as a runaway backstop. **inferred**.

### 1.6 Retries, timeouts, error handlers, graceful drain (all `langgraph>=1.2`)
- `RetryPolicy(initial_interval=0.5, backoff_factor=2.0, max_interval=128.0, max_attempts=3, jitter=True, retry_on=default_retry_on)`
  per node (`add_node(..., retry_policy=...)`) or graph-wide (`set_node_defaults(...)`). **verified**,
  [LG/types.py L427-L446](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L427-L446), [LG/graph/state.py L272-L330](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/graph/state.py#L272-L330).
- `default_retry_on` retries **any** exception except `ValueError, TypeError, ArithmeticError, ImportError, LookupError, NameError, SyntaxError, RuntimeError, ReferenceError, StopIteration, StopAsyncIteration, OSError`; for `requests`/`httpx` only 5xx.
  **verified**, [fault-tolerance.md "Default behavior"](https://docs.langchain.com/oss/python/langgraph/fault-tolerance.md).
  Consequence: `subprocess.CalledProcessError`, PyGithub `GithubException` (incl. 4xx/422) and githubkit
  `RequestFailed` **would be retried** by default — give every deterministic node an explicit `retry_on`
  (network/5xx/429 only). **inferred** (from the exclusion list; those classes are not subclasses of the excluded ones).
- `timeout=` per node: a number = hard `run_timeout`; `TimeoutPolicy(run_timeout, idle_timeout, refresh_on="auto"|"heartbeat")`;
  `runtime.heartbeat()` refreshes the idle clock; raises `NodeTimeoutError` (retryable by default).
  "**Timeouts are supported only for async nodes**; sync nodes cannot be safely cancelled in-process" and "Sync nodes
  with a `timeout` are rejected at compile time". **verified**, [LG/graph/state.py L714-L722](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/graph/state.py#L714-L722), [LG/types.py L461-L527](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L461-L527), fault-tolerance.md "Timeouts".
  → write deterministic nodes as `async def` and run blocking calls via `asyncio.to_thread` or
  `asyncio.create_subprocess_exec` (and still pass `timeout=` to subprocesses). **inferred**.
- `error_handler=` per node (or default via `set_node_defaults`): runs after retries are exhausted, receives
  `error: NodeError` (`.node`, `.error`) and may return `Command(update=..., goto=...)`; "Failure provenance is
  checkpointed" so a crash before the handler finishes replays the same error. **verified**, [fault-tolerance.md "Error handling"](https://docs.langchain.com/oss/python/langgraph/fault-tolerance.md).
  → one default error handler (`set_node_defaults(error_handler=...)`) that routes any unexpected exception to
  `S10_ask` with `return_to=<failed node>` (a human can reply `/oc2 retry` or `/oc2 abort`) is the cheapest
  "never die silently" rule for the prototype (§8.4). **inferred**.
- Graceful drain: `RunControl().request_drain("sigterm")`, `invoke(..., control=control)` raises `GraphDrained` at the
  next super-step boundary; nodes can read `runtime.drain_requested`; resume with `invoke(None, config)`. **verified**,
  [fault-tolerance.md "Graceful shutdown"](https://docs.langchain.com/oss/python/langgraph/fault-tolerance.md), [LG/runtime.py L79-L99, L209, L277](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/runtime.py#L79-L99).
- Durability: `invoke(..., durability="sync"|"async"|"exit")`, default `"async"` ("small risk that LangGraph does not
  write checkpoints if the process crashes"). **verified**, [LG/pregel/main.py L2695-L2696](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/pregel/main.py#L2695-L2696), [checkpointers.md "Durability modes"](https://docs.langchain.com/oss/python/langgraph/checkpointers.md).
  → use `"sync"`: our steps are minutes long, the per-step write cost is irrelevant, and S5/S9 have external effects. **inferred**.
- Pending writes: successful nodes in a failed super-step are not re-run on resume. **verified**, checkpointers.md "Pending writes".

### 1.7 Node caching
- `add_node(..., cache_policy=CachePolicy(key_func=..., ttl=...))` + `compile(cache=InMemoryCache())`. **verified**,
  [graph-api.md "Node caching"](https://docs.langchain.com/oss/python/langgraph/graph-api.md), [LG/types.py L530-L538](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L530-L538).
- Little use in this pipeline: every deterministic step reads live external state (GitHub, git, CI) whose freshness
  matters; caching S1 issue fetches would hide edits to the issue. Do not cache. **inferred**.

### 1.8 Structured outputs for gates
- Deterministic gates (S1, S4, S6, S9) need no LLM: they parse/compute and write typed fields. The LLM-produced
  structures are the builder's `BuildResult` and the reviewer's `ReviewVerdict`; validate them with Pydantic at the
  S3/S7 node boundary and treat a validation failure as a failed attempt (counted, retried once, then S10). **inferred**.
- Typed human answers: `interrupt(payload, response_schema=PydanticModel)` validates the resume value; an invalid value
  raises `ValidationError`, "Nothing is saved, so the interrupt can be answered again" (`is_invalid_resume`). Requires
  `langgraph>=1.2.12`. **verified**, [LG/types.py L903-L1047](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L903-L1047), [interrupts.md "Define an interrupt response schema"](https://docs.langchain.com/oss/python/langgraph/interrupts.md).
- Testing: `compiled.nodes["S6_ci_wait"].invoke(state)` for single nodes; `update_state(..., as_node=...)` +
  `interrupt_after=` for partial runs. **verified**, [test.md](https://docs.langchain.com/oss/python/langgraph/test.md).

---
## 2. GitHub access for S1 / S5 / S9

### 2.1 Library options (metadata via `gh api`, 2026-10-13)

| | **githubkit** | **PyGithub** | **`gh` CLI via subprocess** |
|---|---|---|---|
| Repo / licence | yanyongyu/githubkit, MIT | PyGithub/PyGithub, **LGPL-3.0** | cli/cli, MIT |
| Stars, latest release, last commit | 354; v0.16.1 (2026-08-14); 2026-10-07 — maintained, small team | 7.8k; v2.10.0 (2026-08-20); 2026-10-12 — maintained | 46.7k; v2.102.0 (2026-09-30); 2026-10-12 — maintained (local Mac has 2.74.2) |
| Sync / async | both | sync only | async via `asyncio.create_subprocess_exec` |
| Typing | generated, Pydantic models | typed classes | JSON output only |
| GraphQL | `github.graphql(q, variables)` / `async_graphql` | internal `graphql_named_mutation` behind helpers | `gh api graphql`, `gh pr ready` |
| Ready for review | one GraphQL mutation | `PullRequest.mark_ready_for_review()` | `gh pr ready` (`--undo` converts back) |
| App installation tokens | `AppAuthStrategy(...).as_installation(id, repositories=[...], permissions={...})` | `GithubIntegration.get_access_token(id, permissions)` — **no repository scoping** | none; set `GH_TOKEN` per process |
| Retries | built in: rate limit once, 5xx up to 3×; optional HTTP cache (Hishel) | urllib3 `GithubRetry`, write throttling | none |

Evidence (all **verified**):
- githubkit features (sync+async, REST+GraphQL, auto retry, HTTP cache) — [README L55-L62 @ v0.16.1](https://github.com/yanyongyu/githubkit/blob/d043cb66d21d62e27bf3439c217a41a596c2a8a2/README.md#L55-L62);
  scoped installation tokens — [githubkit/auth/app.py L286-L301](https://github.com/yanyongyu/githubkit/blob/d043cb66d21d62e27bf3439c217a41a596c2a8a2/githubkit/auth/app.py#L286-L301);
  GraphQL — [docs/usage/graphql.md](https://github.com/yanyongyu/githubkit/blob/d043cb66d21d62e27bf3439c217a41a596c2a8a2/docs/usage/graphql.md);
  retry policy — [docs/usage/auto-retry.md](https://github.com/yanyongyu/githubkit/blob/d043cb66d21d62e27bf3439c217a41a596c2a8a2/docs/usage/auto-retry.md).
  Open SWE (11k stars) pins `githubkit[auth-app]==0.16.1` (see `01-complete-workflows.md`), which is a useful adoption signal.
- PyGithub `mark_ready_for_review()` (GraphQL `markPullRequestReadyForReview`) — [github/PullRequest.py L1038-L1060 @ v2.10.0](https://github.com/PyGithub/PyGithub/blob/5cdf6ab395c52efb652d0bc1f28fdf2e452b1b41/github/PullRequest.py#L1038-L1060);
  `create_pull(..., draft=...)` — [github/Repository.py L1840-L1848](https://github.com/PyGithub/PyGithub/blob/5cdf6ab395c52efb652d0bc1f28fdf2e452b1b41/github/Repository.py#L1840-L1848);
  installation token only takes `permissions` — [github/GithubIntegration.py L265-L289](https://github.com/PyGithub/PyGithub/blob/5cdf6ab395c52efb652d0bc1f28fdf2e452b1b41/github/GithubIntegration.py#L265-L289); retry/throttle options — [github/MainClass.py L186-L207](https://github.com/PyGithub/PyGithub/blob/5cdf6ab395c52efb652d0bc1f28fdf2e452b1b41/github/MainClass.py#L186-L207).
- `gh pr checks --json` has a `bucket` field (`pass|fail|pending|skipping|cancel`), `--required`, `--watch`, `--fail-fast`, exit code 8 = pending — [manual: gh pr checks](https://cli.github.com/manual/gh_pr_checks); `gh pr ready [--undo]` and `GH_TOKEN` precedence — `gh pr ready --help`, `gh help environment` (2.74.2).
- There is **no REST way** to leave draft: `PATCH /pulls/{n}` accepts only `title, body, state, base, maintainer_can_modify`; `draft` is a create-time field — [REST pulls](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#update-a-pull-request). GraphQL `markPullRequestReadyForReview` / `convertPullRequestToDraft` exist — live schema introspection (`gh api graphql`, 2026-10-13).

**Recommendation:** **githubkit** for every API call in deterministic nodes: async (LangGraph node timeouts only work on
async nodes, §1.6), typed responses, one library for REST and GraphQL, and least-privilege App tokens scoped to one
repository per call. Keep `gh` as a human/debug tool and as a fallback for the first spike; avoid PyGithub mainly
because it is sync-only and cannot scope App tokens to a repository. **inferred** from the verified facts above.
Note for any library: set an explicit `retry_on` on LangGraph nodes, otherwise 4xx errors are retried (§1.6).

### 2.2 Credentials: GitHub App vs fine-grained PAT

| | GitHub App installation token | Fine-grained PAT |
|---|---|---|
| Lifetime | **1 hour**; mint per node | up to the expiry set at creation |
| Scope | can be narrowed **per token** with `repositories`/`repository_ids` and `permissions` (never above the app's grant) | fixed at creation (repos + permissions) |
| Identity | `<app>[bot]` | the human (PRs authored by Alex — a human reviewer cannot approve their own PR; **inferred**) |
| Checks API | `checks: read` available | **no "Checks" permission exists**; check-run endpoints are not listed for fine-grained PATs; `gh run watch` says it "does not support authenticating via fine grained PATs as it is not currently possible to create a PAT with the `checks:read` permission" |
| Triggers CI on push | yes (unlike `GITHUB_TOKEN`) | yes |
| Long-lived secret | the App private key (keep in macOS Keychain, readable only by the runner) | the PAT itself |

Evidence (**verified**): [Authenticating as an App installation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation) ("expire after 1 hour"; `repositories`/`repository_ids`/`permissions`; `git clone https://x-access-token:TOKEN@github.com/owner/repo.git`);
[fine-grained PAT permissions list](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) (no Checks section; job logs and `rerun-failed-jobs` are under "Actions"; combined status under "Commit statuses");
`gh run watch --help` (2.74.2); [triggering workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow) (App token or PAT, not `GITHUB_TOKEN`, to trigger runs).

**Recommendation:** a dedicated GitHub App installed on the target repo only, and **one token per node with the
minimum permissions**: S1 `issues:read`; S5 `contents:write, pull_requests:write`; S6 `checks:read, actions:read`
(+`actions:write` only if flaky re-runs are enabled); S9 `pull_requests:write, issues:write`; S10 `issues:write`.
A fine-grained PAT is acceptable for a day-one spike if S6 uses the **Actions API** (workflow runs/jobs/logs) instead of
the Checks API — fine for this repo, whose CI is only GitHub Actions. **inferred**.

### 2.3 Keeping tokens out of the agent sandbox (S2/S3/S7 vs S5/S9)
1. The container gets no token env var, no `~/.config/gh`, no SSH agent socket, no host credential helper; the clone's
   `origin` URL has no credentials. **inferred**.
2. Host-side `git push` gets the token for that one process only, through command-scope config in the environment
   (`GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=http.https://github.com/.extraheader`, `GIT_CONFIG_VALUE_0=AUTHORIZATION: basic <base64(x-access-token:TOKEN)>`)
   — never in argv (visible in `ps`) and never in `.git/config`. `GIT_CONFIG_*` are "command" scope, i.e. **protected
   configuration**, overriding config files. **verified** for the mechanism ([git-config ENVIRONMENT + "Protected configuration"](https://git-scm.com/docs/git-config)); the header form is the one
   `actions/checkout` uses (`http.${origin}/.extraheader` = `AUTHORIZATION: basic base64("x-access-token:" + token)`,
   [src/git-auth-helper.ts L57-L64 @ f548e57](https://github.com/actions/checkout/blob/f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a/src/git-auth-helper.ts#L57-L64)) — **verified**;
   unlike checkout we keep it out of `.git/config`.
3. **Do not run host git inside a `.git` the agent could write.** Repository config and hooks live in `$GIT_DIR`
   (`$GIT_DIR/hooks`, `core.hooksPath`; pre-commit/pre-push run on the host during S5) — [githooks](https://git-scm.com/docs/githooks) **verified**.
   An agent that can edit `.git/config` could add a hook, `core.fsmonitor`, or `url.<evil>.insteadOf` /
   `remote.origin.pushurl` and capture the push credential. **inferred** (threat model). Mitigation in §3.3: mount `.git`
   read-only into the container, and run host git with `-c core.hooksPath=/dev/null` and an explicit push URL.
4. A cross-check from the field: Open SWE gives its sandboxes push access through a proxy that injects auth ("never
   sees the token value") but notes "Coding sandboxes normally receive installation-wide GitHub App access"; its
   Managed-Deep-Agents reviewer "holds no GitHub, Slack or database credentials" — see `01-complete-workflows.md`.
   Our design is stricter: the agent cannot push at all; S5 pushes. **verified (via sibling) / inferred**.

### 2.4 S1 Intake (fetch + completeness gate, no LLM)
Pattern:
1. `GET /repos/{o}/{r}/issues/{n}`; reject if the payload has a `pull_request` key ("every pull request [is] an issue")
   or the issue is closed; 301/404/410 → blocked. **verified** ([REST issues](https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28#get-an-issue)).
2. Authorisation gate: only start on a `ready`-style label applied by someone with write access. OpenHands enforces
   exactly this — its "Ready-for-dev Label Policy" workflow looks up the labeller via
   `repos/$REPOSITORY/collaborators/$ACTOR/permission` and removes `ready-for-dev` unless `write|maintain|admin`
   ([issue-readiness-check.yml @ b5d6b2f](https://github.com/OpenHands/OpenHands/blob/b5d6b2ff2c90b3bb2a21a35cd396b61d88990831/.github/workflows/issue-readiness-check.yml), OpenHands 90.8k stars, MIT, active). **verified**.
3. Completeness: parse Markdown sections (markdown-it-py, MIT, 1.4k stars, v4.2.0 2026-05-07; or a regex on `^#{1,4} `)
   and require a non-empty section whose heading matches a configured alias list (`Acceptance criteria`, `Done when`,
   `Expected`) or at least one `- [ ]` item. Do not rely on issue-form `validations: required`: GitHub documents it as
   "Only for public repositories" and this repo is private. **verified** ([form schema](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema); `gh repo view` → PRIVATE).
   Our own issues show why aliases are needed: #213 has `## Acceptance criteria`, #160 has only step check-lists,
   #223 has only `**Ask:**` (**verified**, `gh issue view`, 2026-10-13).
4. Snapshot `issue_title`, `issue_body`, `issue_updated_at` into state; the builder works from the snapshot. At S9,
   compare `updated_at` and mention a changed spec in the summary. **inferred**.
5. Incomplete → `S10_ask` with a templated question ("add acceptance criteria"); the answer can be a comment or an
   edited issue body, so on resume S1 re-fetches and re-gates. **inferred**.
Other examples: OpenHands resolver triggers on a `fix-me` label and opens a draft PR on success
([OpenHands blog](https://www.openhands.dev/blog/open-source-coding-agents-in-your-github-fixing-your-issues)); Open SWE v1
uses an **LLM** classifier for intake (see `01-complete-workflows.md`) — the opposite of what S1 wants.

### 2.5 S5 Publish (commit, push, draft PR — the only node with write credentials)
Each effect is a separate `@task` inside the node (crash-safe, §1.1) and is idempotent by **read-before-write**:
1. `commit`: host git with explicit `--git-dir/--work-tree`, `-c core.hooksPath=/dev/null`, fixed author/committer
   (`<app>[bot]`), message from a template (`<type>(<scope>): <title> (#<issue>)`). `git add -A`, then if
   `git diff --cached --quiet` says nothing changed → route back to S3 ("no changes") or S10 after N times. If the
   commit already exists (crash after commit, before push), the task result is restored from the checkpoint and
   not re-run. **inferred**.
2. `push`: `git push --force-with-lease=refs/heads/<branch>:<last_pushed_sha or ''> origin HEAD:refs/heads/<branch>`.
   An empty `<expect>` means "the named ref must not already exist", so the very first push cannot clobber a human's
   branch, and later pushes fail if anyone else pushed — route that to S10. **verified** semantics ([git-push](https://git-scm.com/docs/git-push)); routing **inferred**.
3. `open_pr`: first `GET /repos/{o}/{r}/pulls?head=<owner>:<branch>&state=open` ("user:ref-name" format, **verified**,
   [REST pulls](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-pull-requests)); create with
   `draft=true` only if none exists; body = template + `Fixes #<n>` + hidden marker `<!-- oc2:thread=<thread_id> -->` so
   the PR can be mapped back to the LangGraph thread. **inferred** (Open SWE v1 also prepends `Fixes #<issue>` in code — `01-complete-workflows.md`).
4. Store `pr_number`, `pr_node_id`, `head_sha` (the SHA you pushed — S6 must poll exactly this SHA).
5. Wait at least 1 s between mutating calls ("wait at least one second between each request") — **verified**,
   [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).
Examples of the same create-or-update discipline (**verified**):
- `peter-evans/create-pull-request` (2.9k★, MIT, v8.1.1, pushed 2026-10-12): "If a pull request already exists it will
  be updated if necessary … If no update is required the action exits silently"; `draft: true` applies "only on create",
  `always-true` on create and update ([README L75, L174 @ bd09a93](https://github.com/peter-evans/create-pull-request/blob/bd09a93810788ce61d2d5fb7d6b221b9b4a4aab7/README.md#L174)).
- Open SWE v1 `open-pr` node: deterministic `git diff --name-only` check, commit/push with the App installation token,
  then `createPullRequest` **or** `updatePullRequest` (see `01-complete-workflows.md`).
- OpenHands resolver: draft PR on success, otherwise push a branch and comment ([blog](https://www.openhands.dev/blog/open-source-coding-agents-in-your-github-fixing-your-issues)).

### 2.6 S9 Merge-ready (never merge)
1. Re-read the PR via GraphQL: `headRefOid == state.head_sha`, `isDraft`, `mergeable`, `mergeStateStatus`,
   `reviewDecision`, `statusCheckRollup` (fields confirmed by live introspection). `MergeStateStatus` values: `CLEAN`,
   `UNSTABLE` ("Mergeable with non-passing commit status"), `BLOCKED`, `BEHIND`, `DIRTY`, `HAS_HOOKS`, `UNKNOWN`
   (`DRAFT` is deprecated). **verified** (`gh api graphql` introspection, 2026-10-13).
2. Head moved (someone else pushed — only S5 pushes, and it runs before S9) → S10; `CONFLICTING`/`DIRTY` → S10 (or a base-sync step) —
   note "Workflows will not run on `pull_request` activity if the pull request has a merge conflict", so a conflicted
   PR would otherwise sit in S6 forever. **verified** ([events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)).
3. `markPullRequestReadyForReview` only if `isDraft` (idempotent). This repo's `ci.yml` uses `on: pull_request:` with the
   default types (`opened, synchronize, reopened`), so leaving draft does **not** start another CI run and S9 need not
   wait again. **verified** (`.github/workflows/ci.yml` L3-L7; default types per the same GitHub page).
4. Post or update one summary comment keyed by `<!-- oc2:summary -->` (search existing comments first); add a
   `merge-ready` label (idempotent). Then `END`. **inferred**.
5. "Merge-ready" must be our own predicate, not GitHub's: this repo's `main` ruleset has only `deletion`,
   `non_fast_forward` and `pull_request` (0 approvals) rules and classic protection has no required checks, so GitHub
   will not mark `lint`/`validate`/`unit` as required (`gh pr checks --required` → empty). Configure
   `required_checks = {("CI","lint"), ("CI","validate"), ("CI","unit")}` (workflow, job — see §5.1 for why not bare
   names) in the workflow and union it with whatever rulesets/branch protection
   report (as Open SWE's `RequiredCheck.for_branch()` does). **verified** (`gh api repos/bodegus/openclaw2-deploy/rules/branches/main`,
   `.../branches/main`, 2026-10-13; [open-swe ci.py L62-L103](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/github/ci.py#L62-L103)).

---
## 3. S2 Workspace — git library, worktree vs clone, container per task

### 3.1 Git library

| Option | Facts (2026-10-13) | Verdict |
|---|---|---|
| **plain `git` CLI** (`asyncio.create_subprocess_exec`) | full feature parity, easy to log/replay, `timeout=`; local git 2.50.0 (Homebrew) | **recommended** |
| GitPython 3.2.0 (BSD-3, 5.2k★, release 2026-09-30) | README: "This project is in **maintenance mode** … no feature development … no bug fixes, unless they are relevant to the safety of users"; it is "often backed by calling the `git` command-line program" — [README L26-L38 @ 3.2.0](https://github.com/gitpython-developers/GitPython/blob/6a7180a9dfcb276755a8af99dd78155f775a6b14/README.md#L26-L38) **verified** | adds a layer over the same binary |
| pygit2 1.20.1 (libgit2 bindings, GPLv2 with linking exception, 1.7k★) | libgit2 lags git: `extensions.relativeworktrees` (git 2.48) was unsupported until [libgit2#7099](https://github.com/libgit2/libgit2/issues/7099) closed 2026-08-28 **verified** | feature lag, credential callbacks |
| dulwich 1.2.17 (pure Python, 2.3k★) | maintained | slower, less complete (**inferred**) |

Wrapper rules (**inferred**): explicit argv (never `shell=True`), `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`,
`-c core.hooksPath=/dev/null`, `-c core.fsmonitor=false`, a per-call timeout, and capture of stdout/stderr into the
task's artifact log (never into LangGraph state beyond a trimmed tail).

### 3.2 Worktree vs fresh clone
- Worktrees **share** all `refs/` (except a few), objects and, by default, the repository config; each linked
  worktree's `.git` is a file pointing at `$GIT_DIR/worktrees/<id>` with an **absolute** path unless
  `--relative-paths` / `worktree.useRelativePaths` is used (git ≥ 2.48; enables an extension older git cannot read).
  **verified**, [git-worktree](https://git-scm.com/docs/git-worktree), [Git 2.48 release notes](https://github.com/git/git/blob/master/Documentation/RelNotes/2.48.0.adoc).
  → Bind-mounting a worktree into a container breaks `git` inside it unless the main repo's `.git` is mounted at the
  same path, and then the agent can write shared refs/config of every task. **inferred**.
- **Recommendation:** one bare mirror per target repo on the host (`git clone --mirror`, `git fetch --prune` at S2),
  then a **self-contained per-task clone** `git clone --local <mirror> <task>/repo` (objects hard-linked, cheap) and
  `git switch -c oc2/<issue>-<slug> origin/main`; reset `origin` to the plain https URL. No shared mutable git state
  between tasks; deleting the task dir is the cleanup. **inferred**.

### 3.3 Container per task (agent sandbox), git metadata read-only
```
~/.oc2/mirrors/<owner>__<repo>.git            host only (S2 fetch)
~/.oc2/tasks/<thread_id>/repo/                RW bind mount -> /work           (agent edits files)
~/.oc2/tasks/<thread_id>/repo/.git            RO bind mount -> /work/.git      (agent can run git status/diff/log, cannot commit or plant hooks/config)
~/.oc2/tasks/<thread_id>/artifacts/           host only (gate logs, CI logs, patches)
~/.oc2/state/checkpoints.sqlite               host only, never mounted
```
- docker-py 7.2.0 (Apache-2.0, 7.2k★, release 2026-07-09, last commit 2026-09-15) `containers.run(...)` supports
  `volumes`/`mounts` (bind + `ro`/`rw`), `network_mode="none"`, `mem_limit`, `pids_limit`, `read_only`, `cap_drop`,
  `security_opt`, `user`, `working_dir`, `init`, `tmpfs`, `auto_remove`; `Container.exec_run(...)` has **no timeout
  parameter**. **verified**, [docker-py containers docs](https://docker-py.readthedocs.io/en/stable/containers.html).
  → wrap execs as `timeout <secs> <cmd>` inside the container, or drive `docker exec` with
  `asyncio.create_subprocess_exec(..., timeout)`. Async alternatives: aiodocker 0.27.0 (Apache-2.0, 538★),
  python-on-whales 0.81.0 (MIT, 712★, wraps the docker CLI). **verified** metadata / **inferred** fit.
- Run the container with `--cap-drop ALL --security-opt no-new-privileges --pids-limit --memory --cpus --read-only`
  root FS + `tmpfs /tmp`, non-root `user`, labels `oc2.thread=<id>` for supervision/cleanup, and **no** GitHub token,
  no gh config, no SSH agent socket. Network: `none` for S4, an egress-allowlist network for the builder if it must
  install dependencies. **inferred** (sandbox depth is covered in `02-builder-reviewer-harness.md`).
- The RO `.git` overlay on top of the RW work-tree mount is the same nested-mount trick as the common
  `-v $PWD:/app -v /app/node_modules` pattern; it must be checked once on this Mac (`git status`, `git diff` work;
  `git commit` fails; no index-lock errors are fatal). **inferred — run a 5-minute experiment**.
- **This Mac runs Docker through Colima** (`docker context ls` → `colima *`; engine 27.4.0, Ubuntu 24.04 aarch64 VM).
  Colima's default is "`$HOME` is mounted as writable" (`mounts: []`; `mountType` virtiofs for vz, sshfs for qemu) —
  so task directories must live under `$HOME` (not `/private/tmp`) to be bind-mountable. **verified**
  ([colima embedded/defaults/colima.yaml L204-L272 @ ad7a860](https://github.com/abiosoft/colima/blob/ad7a86041b9e93b24b30cc6b89451e6fd599f6dc/embedded/defaults/colima.yaml#L204-L272); local `docker info`).
  (Docker Desktop would share `/Users, /Volumes, /private, /tmp, /var/folders` — [settings docs](https://docs.docker.com/desktop/settings-and-maintenance/settings/).)
- Handoff to S5: the host commits in `~/.oc2/tasks/<id>/repo` with its own git (§2.5). Fallback if the RO-`.git` mount
  proves awkward: give the agent a private RW clone and hand back a `git diff --binary` patch that the host applies
  with `git apply --index` to a host-only clone — the only thing crossing the trust boundary is a patch file.
  Avoid `git fetch`/`clone` *from* the agent-controlled repo on the host (local-clone code-execution CVEs exist,
  e.g. [CVE-2024-32004](https://github.com/git/git/security/advisories/GHSA-xfc6-vwr8-r389) "Remote Code Execution while cloning special-crafted local repositories", fixed 2024-05-14 — **verified**). The patch route is **inferred**.

### 3.4 Examples seen
1. Open SWE: one persistent sandbox per thread, providers LangSmith/Daytona/Modal/Runloop/E2B/local; v2 lets the
   agent clone itself (see `01-complete-workflows.md`). **verified via sibling**.
2. OpenHands resolver: runs in GitHub Actions; draft PR on success, pushes a branch otherwise ([blog](https://www.openhands.dev/blog/open-source-coding-agents-in-your-github-fixing-your-issues)). **verified (secondary)**.
3. Worktree-per-agent setups are popular for parallel local agents (e.g. [DEV post](https://dev.to/recca0120/git-worktree-multiple-working-directories-per-repo-and-the-key-to-parallel-ai-agents-40)),
   but they assume the agent runs on the host, not in a container. **inferred**.

---

## 4. S4 Local gate (deterministic test/lint; failure → S3, bounded)

Pattern (**inferred** unless marked):
- Commands come from **workflow config per target repo**, never from the agent or the issue. Run them in a **fresh**
  container from the same image (not the builder's long-lived one), with the work tree mounted **read-only** plus
  tmpfs caches, `network_mode="none"`, a wall-clock timeout, and `TimeoutPolicy(run_timeout=...)` on the node.
- Before tests, a cheap **diff policy check** in plain Python on the uncommitted work-tree changes (the agent cannot
  commit): `git status --porcelain=v1 -z --untracked-files=all` (host side, explicit `--git-dir`):
  protected paths (`.github/workflows/**`, CI scripts, lock files, test fixtures you never want weakened) → S10 for
  human approval; empty diff → back to S3 ("nothing changed"); diff size above a limit → S10. Optional secret scan
  (gitleaks 8.30.1, MIT, 29.9k★, last commit 2026-07-22; Yelp detect-secrets 1.5.0, Apache-2.0, last release 2024-05 —
  less active). **verified** metadata.
- Output to state: `local_gate = {"passed": bool, "failed_commands": [...], "log_tail": "<last 200 lines, ANSI stripped>"}`;
  full logs to `artifacts/`. Router: pass → S5; fail and `local_gate_failures < 3` → S3 with the tail;
  same failure fingerprint twice in a row (hash of failing command + first error line) → S10 "stuck".
- **Repo-specific constraint (verified):** this repo's CI entrypoint refuses to run off Linux/amd64 —
  `[ "$(uname -s)/$(uname -m)" = Linux/x86_64 ] || { echo 'CI requires native Linux AMD64' ...; exit 1; }`
  ([ops/ci.sh L19](https://github.com/bodegus/openclaw2-deploy/blob/5aff4a29c7e23079ecbe565491bba2b779d71ad3/ops/ci.sh#L19)), and CI calls
  `sh ops/ci.sh lint|validate|unit` ([.github/workflows/ci.yml L50, L66, L86](https://github.com/bodegus/openclaw2-deploy/blob/4843208ccbd4b5b6ecc764a499aea0fccf07acd4/.github/workflows/ci.yml#L50)).
  On the Apple-Silicon Colima VM (aarch64) S4 therefore **cannot** mirror CI for openclaw2-deploy; treat S4 as an
  optional fast pre-filter configured per target repo (e.g. `python -m pytest tests/unit -q` in a python image) and
  S6 as the authoritative gate. **inferred** from the verified script.
Examples of the same gate-and-reflect loop (**verified**):
- **Aider** (Aider-AI/aider, 49.5k★, Apache-2.0, last commit 2026-05-22): after each edit it runs the linter and, with
  `--auto-test`, the `--test-cmd`; a non-zero exit becomes a "reflected message" sent back to the model, capped by
  `max_reflections = 3` ("Only 3 reflections allowed, stopping") —
  [aider/coders/base_coder.py L100-L101, L932-L943, L1598-L1622 @ 5dc9490](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/coders/base_coder.py#L1598-L1622);
  [docs: linting and testing](https://aider.chat/docs/usage/lint-test.html). Here the gate is plain code and the cap is a counter — exactly S4 → S3.
- LangGraph code-assistant example: generate → `code_check` (exec imports + code) → route back with the error while
  `iterations < max_iterations` (§6.2).
- Counter-example: Open SWE v2 has no deterministic gate node at all — "the process lives in prompts, skills and ~35
  middleware classes" (`01-complete-workflows.md`), i.e. the pattern we are moving away from. **verified via sibling**.

---
## 5. S6 CI wait without an LLM

### 5.1 What to read (all keyed by the exact `head_sha` that S5 pushed)
| Source | Endpoint | Notes |
|---|---|---|
| Check runs | `GET /repos/{o}/{r}/commits/{sha}/check-runs?filter=latest` | `filter=latest` (default) "returns the most recent check runs"; limited to the 1000 most recent check suites. Needs `checks:read` → **App token** (no fine-grained PAT permission). **verified** ([REST check runs](https://docs.github.com/en/rest/checks/runs?apiVersion=2022-11-28#list-check-runs-for-a-git-reference)) |
| Legacy statuses | `GET /repos/{o}/{r}/commits/{sha}/status` | "Commit statuses" permission (PAT ok). **verified** (fine-grained list) |
| Workflow runs → jobs → steps | `GET /actions/runs?head_sha=<sha>`, `GET /actions/runs/{id}/jobs?filter=latest` | `head_sha` filter exists; jobs carry `steps[]` with `name, number, status, conclusion, started_at, completed_at` and `check_run_url`. "Actions: read" (PAT ok). **verified** ([workflow runs](https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28#list-workflow-runs-for-a-repository), [jobs](https://docs.github.com/en/rest/actions/workflow-jobs?apiVersion=2022-11-28#get-a-job-for-a-workflow-run)) |
| One-call rollup | GraphQL `pullRequest { headRefOid mergeable statusCheckRollup { state contexts { ... on CheckRun {name status conclusion isRequired(pullRequestNumber:) checkSuite{workflowRun{databaseId}}} ... on StatusContext {context state} } } }` | **verified** live on this repo (PR #232). Handy for S6 + S9 together |
| Mergeability | `GET /pulls/{n}` → `mergeable` true/false/null | null = background job still computing; poll again. **verified** ([git database guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-your-git-database?apiVersion=2022-11-28)) |

Repo-specific facts that shape S6 (all **verified** on bodegus/openclaw2-deploy, 2026-10-13):
- **Check names are not unique**: PR #232's head `fae47cb` has two `validate` check runs — one from workflow
  `CI` (`ci.yml`) and one from `Images` (`images.yml`). Key required checks by **(workflow, job)**, not by name.
- `images.yml` has a `paths:` filter, so some PRs get its checks and some do not → never "wait for all checks";
  wait for the configured required set (§2.6) and treat the rest as advisory.
- `ci.yml` cancels superseded PR runs (`cancel-in-progress: ${{ github.event_name == 'pull_request' }}`,
  [ci.yml L16-L23](https://github.com/bodegus/openclaw2-deploy/blob/4843208ccbd4b5b6ecc764a499aea0fccf07acd4/.github/workflows/ci.yml#L16-L23)) →
  `cancelled` on an *old* SHA is noise; always filter by the current `head_sha`.
- GitHub job id == check-run id for Actions jobs (`check_run_url` of job 115016972812 ends in the same id).

### 5.2 Classification — a pure, unit-tested function
States: `pending | success | failure | blocked | missing | conflict | head_moved | timeout`. Rules:
- Any required (workflow, job) completed with `failure | timed_out | action_required | startup_failure` → `failure`.
- Any required check not yet reported, or queued/in_progress → `pending`. "No checks yet" is **pending, not success**.
- All required completed with `success | neutral | skipped` → `success`; a required check `cancelled`/`stale` on the
  current SHA → `blocked` (infra/human; optionally one re-run first, §5.5).
- No check at all after `ci_start_grace` (e.g. 10 min) → `missing` (workflow disabled, Actions outage, path filter,
  or merge conflict — "Workflows will not run on `pull_request` activity if the pull request has a merge conflict",
  **verified**). Check `mergeable` first so a conflict is reported as `conflict`, not `missing`.
- PR `headRefOid != state.head_sha` → `head_moved` (someone else pushed; never wait on a SHA we did not push).
Precedents (**verified**): Open SWE's `aggregate_check_state()` returns `pending | success | blocked | failure`, treats an
empty check set as pending and `cancelled/stale` as blocked ([baby_sit.py L362-L410](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/baby_sit.py#L362-L410));
its `RequiredCheck.for_branch()` merges branch protection **and** rulesets and pins the reporting App
([ci.py L62-L103](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/github/ci.py#L62-L103)).
Renovate (22.7k★, AGPL-3.0) bounds "pending forever" with `prNotPendingHours` ("Maximum hours to wait for PR status
checks…", default 25) measured from the last commit time ([docs](https://docs.renovatebot.com/configuration-options/#prnotpendinghours);
[lib/workers/repository/update/pr/index.ts L228-L283 @ ad515fb](https://github.com/renovatebot/renovate/blob/ad515fb96264b96495b567bf8177dd359d2c0108/lib/workers/repository/update/pr/index.ts#L228-L283)).
`gh pr checks --json bucket` gives the same five-way bucketing (`pass|fail|pending|skipping|cancel`) from the CLI.

### 5.3 How to wait
| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Poll inside the S6 node** (recommended for the Mac prototype) | async loop: read → classify → `runtime.heartbeat()` → `asyncio.sleep(backoff)`; node `timeout=TimeoutPolicy(run_timeout=90 min, idle_timeout=5 min, refresh_on="heartbeat")`; deadline stamped in state by S5 | no extra infra; latency ≤ poll interval; a crash just re-enters the node and re-reads (pure read, idempotent) | holds a process for the CI duration |
| B. `interrupt({"kind":"ci_wait","head_sha":…})` + external sensor | launchd/cron tick or webhook resumes with `Command(resume=…)` | nothing held while CI runs; same sensor can detect human pushes/comments | more moving parts (sensor, dedupe, locks) |
| C. `gh pr checks <n> --required --watch --fail-fast` subprocess | exit code 8 = pending | zero code | name-only matching (duplicate `validate` problem), and `--required` is empty on this repo |

- The infrastructure trade-off (A vs B), durable timers (none in LangGraph) and launchd behaviour are researched in
  `04-durability-and-packaging.md` §2; its recommendation is the same (A for S6, B for S10). **verified via sibling**.
- Recursion budget: polling **inside** one node costs one super-step however long CI takes; a `check → sleep → check`
  self-loop costs 2 super-steps per poll and resets only on a new invocation (§1.5). Prefer the in-node loop. **inferred**.
- Rate limits: "Making a conditional request does not count against your primary rate limit if a `304` response is
  returned"; obey `retry-after` / `x-ratelimit-reset`; GitHub prefers webhooks over polling. **verified**
  ([REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)).
  githubkit's optional Hishel HTTP cache should turn repeat polls into conditional requests (**inferred** — check
  on first run). Budget without ETags: 3 calls/poll × 2 polls/min × 60 min ≈ 360 requests per CI wait (**inferred**).
- Graceful stop: check `runtime.drain_requested` each loop and return `{"ci_status": "pending"}`; the router sends
  `pending` back to S6 and `GraphDrained` stops the run at that boundary; `invoke(None, config)` resumes. **inferred**
  from verified drain semantics (§1.6).

### 5.4 Failing-job logs for the builder (deterministic fetch + trim)
- Per failed job: `GET /actions/jobs/{job_id}/logs` → redirect to a **plain-text** log; the link "expires after 1
  minute". **verified** ([REST jobs](https://docs.github.com/en/rest/actions/workflow-jobs?apiVersion=2022-11-28#download-job-logs-for-a-workflow-run)).
- Avoid the run-level zip for this purpose: `gh run view --log-failed` documents that "gh may not always be able to
  associate jobs with their corresponding logs" in the zip, falls back to per-job API fetches (fails above 25), and
  may label lines `UNKNOWN STEP`. **verified** ([pkg/cmd/run/view/view.go L115-L127 @ v2.102.0](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/pkg/cmd/run/view/view.go#L115-L127)).
- Shape of a real log (failed `unit` job, run 38311059391, 2026-10-12; content not copied): 2,895 lines / 240 KB;
  UTF-8 BOM; **every** line prefixed `YYYY-MM-DDThh:mm:ss.fffffffZ `; step boundaries are `##[group]Run …` /
  `##[endgroup]`; one `##[error]` line (the "Process completed with exit code 1" marker) at line 2,871, with the test
  summary in the ~25 lines just above it. Its check-run annotations were only the generic exit-code failure plus a
  Node 20 deprecation warning — **annotations alone are useless here**. **verified** (`gh api`, structure only).
- Trimming recipe (**inferred**): strip BOM, timestamps and ANSI; cut out the failed step (`steps[].conclusion ==
  "failure"`: from its `##[group]Run` line to the next group, or by `started_at/completed_at` window); keep every
  `##[error]`/`##[warning]` line, the last ~150 lines before the first `##[error]`, and annotations with a real
  `path:line`; cap at ~8 KB per job and ~16 KB total; write the full log to `artifacts/` and pass its path too.
  Wrap the text as untrusted data (Open SWE wraps CI data in `<untrusted-ci-data>` — `01-complete-workflows.md`).
- Store a **failure fingerprint** = sha256(workflow, job, failed step name, first error line with digits/paths
  normalised). Same fingerprint after the builder's fix → count a "no progress" strike (§6.3).

### 5.5 Re-runs and flaky tests
- `POST /repos/{o}/{r}/actions/runs/{run_id}/rerun-failed-jobs` (body `enable_debug_logging`), "Actions: write";
  `gh run rerun --failed` is the CLI form. **verified** ([workflow runs](https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28), fine-grained list, `gh run rerun --help`).
- Policy (**inferred**): at most **one** automatic re-run per head SHA, only when the failure looks like infra
  (`cancelled`, `startup_failure`, runner lost, known-flaky job list in config) — never for assertion failures; then
  `failure` goes to S3 with the trimmed log. Count re-runs in `ci_reruns`; Open SWE similarly bounds per-head work
  with `MAX_RETRIES_PER_HEAD = 3` and a `sha256(head_sha|retry:N)` dispatch key
  ([baby_sit.py L40-L41, L386-L387](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/baby_sit.py#L40-L41)). **verified** for Open SWE.

### 5.6 S6 skeleton (async, no LLM)
```python
FAILING = {"failure", "timed_out", "action_required", "startup_failure"}
PASSING = {"success", "neutral", "skipped"}

def classify(required: set[tuple[str, str]], jobs: list[Job], now: float, s: CiClock) -> str:
    """Pure. required = {(workflow_name, job_name)}; jobs = latest jobs for head_sha."""
    seen = {(j.workflow, j.name): j for j in jobs}
    if any(seen.get(k) and seen[k].status == "completed" and seen[k].conclusion in FAILING for k in required):
        return "failure"
    if all(k in seen and seen[k].status == "completed" and seen[k].conclusion in PASSING for k in required):
        return "success"
    if any(k in seen and seen[k].status == "completed" and seen[k].conclusion not in PASSING | FAILING for k in required):
        return "blocked"                                  # cancelled / stale on *this* sha
    if not jobs and now - s.pushed_at > s.start_grace:
        return "missing"
    if now - s.pushed_at > s.deadline:
        return "timeout"
    return "pending"

async def s6_ci_wait(state: PipelineState, runtime: Runtime[Ctx]) -> dict:
    gh = await runtime.context.github(permissions={"checks": "read", "actions": "read", "pull_requests": "read"})
    clock, delay = CiClock.from_state(state), 15
    while True:
        pr = await gh.pr_snapshot(state["pr_number"])                 # headRefOid, mergeable
        if pr.head_sha != state["head_sha"]:
            return {"ci_status": "head_moved"}
        if pr.mergeable == "CONFLICTING":
            return {"ci_status": "conflict"}
        jobs = await gh.latest_jobs_for_sha(state["head_sha"])         # runs?head_sha= → jobs?filter=latest
        status = classify(runtime.context.required_checks, jobs, time.time(), clock)
        runtime.heartbeat()
        if status != "pending" or runtime.drain_requested:
            return {"ci_status": status, "ci_jobs": [j.summary() for j in jobs]}
        await asyncio.sleep(delay)
        delay = min(delay * 2, 120)

builder.add_node("S6_ci_wait", s6_ci_wait,
                 timeout=TimeoutPolicy(run_timeout=95 * 60, idle_timeout=5 * 60, refresh_on="heartbeat"),
                 retry_policy=RetryPolicy(max_attempts=5, retry_on=is_transient_http_error))
builder.add_node("S6_fetch_failure_logs", s6_fetch_failure_logs)    # separate node: own retries, writes ci_failure_report
builder.add_node("S6_rerun_failed", s6_rerun_failed)                # optional, writes ci_reruns += 1
```

---
## 6. S8 Review-fix loop control

### 6.1 The rules we already have, as prose (to be turned into router code)
This repo's conductor prompt already states the S8 policy (**verified**):
- "`approve` for the expected head advances; `blocked` stops. On `request-changes`, give the exact review file … to a
  builder on the same task and branch, then require a fresh review of the new head. Every finding needs a
  disposition: fixed with commit evidence, declined with a specific reason, or deferred with reason and tracking.
  Scope or design disagreement goes to the owner." — [agents/active/conductor/SOUL.md L82-L91](https://github.com/bodegus/openclaw2-deploy/blob/82e296b584f07104575ae5317312c33d8b752bf2/agents/active/conductor/SOUL.md#L82-L91)
- Re-review must recompute the **full** `git diff <base>..<head>`, not only the claimed lines —
  [review-cycle.md L77-L83](https://github.com/bodegus/openclaw2-deploy/blob/84d4ee61067bfa68eba6e4d76d9b95348af9c0a6/agents/active/conductor/skills/review-cycle.md#L77-L83).
- Decision vocabulary `implement | decline | defer`; "Deferred findings are unfinished work"; "A credible unresolved
  blocker stays visible even if you decline its suggested fix." — [.agents/skills/review-and-fix/SKILL.md L60-L78](https://github.com/bodegus/openclaw2-deploy/blob/417acd7acdd1055716ac1b3a7433f180b9a7f39e/.agents/skills/review-and-fix/SKILL.md#L60-L78).
In the graph, all of this becomes **data + a router**; no agent has to remember it.

### 6.2 Bounded-loop examples
1. LangGraph code-assistant example (archival, still in the repo): `iterations: int` in `GraphState`,
   `max_iterations = 3`, router `decide_to_finish` returns `"end"` when `error == "no" or iterations == max_iterations`
   ([examples/code_assistant/langgraph_code_assistant_mistral.ipynb @ 1.2.15](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/examples/code_assistant/langgraph_code_assistant_mistral.ipynb)). **verified**.
   Note it ends the same way on success and on exhaustion — ours must route exhaustion to `S10_blocked`.
2. LangGraph docs "Evaluator-optimizer": structured `Feedback(grade: Literal["funny","not funny"], feedback: str)` via
   `with_structured_output`, router maps grade → `END` or back to the generator — and has **no iteration cap**
   ([workflows-agents.md](https://docs.langchain.com/oss/python/langgraph/workflows-agents.md)). **verified**. Shape to copy, bound to add.
3. Open SWE v1: `reviewsCount` with `maxReviewCount ?? 3` in `routeToReviewOrConclusion`; reviewer verdict forced
   through two tools (`mark_task_completed` / `mark_task_not_complete`) — see `01-complete-workflows.md`. **verified via sibling**.
4. Open SWE v2 per-head bound `MAX_RETRIES_PER_HEAD = 3` for CI-fix dispatches (§5.5). **verified**.

### 6.3 Recommended S8 data model and stopping rules (**inferred**)
```python
class Finding(TypedDict):
    id: str                 # stable: sha1(path, rule/category, normalised message)[:10] — the fingerprint
    severity: Literal["blocker", "major", "minor", "nit"]
    path: str | None
    line: int | None
    message: str
    raised_in_round: int

class Disposition(TypedDict):
    finding_id: str
    decision: Literal["fixed", "declined", "deferred"]
    evidence: str           # fixed: changed paths + covering test (S5 adds the commit sha); declined: reason; deferred: issue/URL
    round: int

class ReviewVerdict(TypedDict):          # produced by S7, validated with Pydantic at the node boundary
    head_sha: str           # must equal state["head_sha"] or the verdict is discarded
    verdict: Literal["approve", "request_changes", "blocked"]
    findings: list[Finding]
```
Router `route_after_review(state)`:
1. `verdict.head_sha != state.head_sha` → `S7_review` again (stale verdict; counts as a review attempt).
2. `blocked` → `S10_ask` (reviewer could not review: missing context, scope question).
3. `approve` and no open blocker/major → `S9_merge_ready`.
4. `request_changes`:
   - `review_round >= MAX_REVIEW_ROUNDS` (3) → `S10_blocked("review rounds exhausted")`.
   - **Two-strike rule**: a finding id that the builder `declined` and the reviewer raises again → strike 1, carry it
     with the builder's reason into the next round; raised a third time (strike 2) → `S10_ask` with both arguments
     (that is "scope or design disagreement goes to the owner").
   - **No-progress rule**: the set of open finding ids is identical to the previous round, or the new diff hash equals
     an earlier round's diff hash (A→B→A oscillation) → `S10_blocked("no progress")`.
   - otherwise → `S3_build` with `{findings, previous dispositions}`; `review_round += 1`.
5. Builder output must contain one disposition per open finding id; a missing disposition fails S3's output
   validation (counts as a failed build attempt), it is not silently accepted.
6. `deferred` requires a tracking reference; S9 lists deferred items in the summary comment. Deferring a `blocker`
   is not allowed by the router (→ S10).
After S3 the normal path S4 → S5 → S6 → S7 runs again, so every fix round is re-tested locally, re-pushed and re-run
in CI before the next review; this is what "fresh review of the new head" means in code.

Optional (**verified** API, **inferred** use): mirror findings into GitHub review threads so humans see them —
GraphQL `addPullRequestReview`/`addPullRequestReviewThread`, `PullRequestReviewThread.isResolved`/`isOutdated`, and
`resolveReviewThread`/`unresolveReviewThread` exist (live introspection, 2026-10-13). S5 can resolve threads for
`fixed` findings and reply with the reason for `declined`; S9 can require "no unresolved bot threads".

---
## 7. S10 Blocked / escalate (human in the loop)

### 7.1 Mechanics (all **verified**, LangGraph 1.2.15)
- `answer = interrupt(payload, response_schema=HumanDecision)` pauses; requires a checkpointer and a `thread_id`; the
  payload must be JSON-serialisable; the caller's `invoke` returns and the thread "waits indefinitely".
  [interrupts.md](https://docs.langchain.com/oss/python/langgraph/interrupts.md), [LG/types.py L903-L1047](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L903-L1047).
- Resume from **any process, any time** with `graph.invoke(Command(resume=value), {"configurable": {"thread_id": t}})`;
  several pending interrupts: `Command(resume={interrupt_id: value, ...})`. Same page, "Handling multiple interrupts".
- Find what a thread is waiting for: `graph.get_state(config).interrupts` — "When reading the latest state … this
  contains only interrupts still waiting for an answer" ([LG/types.py L728-L735](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L728-L735)).
  With `invoke(..., version="v2")` the result is a `GraphOutput` with `.value` and `.interrupts`
  ([LG/types.py L380-L424](https://github.com/langchain-ai/langgraph/blob/08a345637fb2bd499f69c90056a22c478a468817/libs/langgraph/langgraph/types.py#L380-L424)); dict-style access on a `GraphOutput` warns `LangGraphDeprecatedSinceV11`,
  while the default (v1) `invoke` still returns a dict with `__interrupt__`.
- Typed answers: with `response_schema=<Pydantic model>` an invalid answer raises `ValidationError`, nothing is saved,
  and the interrupt can be answered again (`is_invalid_resume`). Requires `langgraph>=1.2.12`.
- **The interrupted node re-runs from its first line on resume**; "Side effects called before `interrupt` must be
  idempotent … Separate side effects into separate nodes when possible". Issue
  [langgraph#6208](https://github.com/langchain-ai/langgraph/issues/6208) "Do not re-execute a node that interrupted
  unless all of its interrupts have been resumed" is still **open** (opened 2025-09-26). A 2026-03 write-up of the same
  trap: [blog.raed.dev](https://blog.raed.dev/posts/langgraph-hitl/).

### 7.2 Pattern: two nodes — `S10_ask` (side effect) then `S10_wait` (interrupt)
```python
class HumanDecision(BaseModel):          # parsed deterministically from the reply
    action: Literal["answer", "retry", "abort", "approve_protected_paths"]
    text: str = ""
    responder: str                       # GitHub login, checked by the sensor

async def s10_ask(state, runtime):       # idempotent: one comment per (thread, ask_seq)
    marker = f"<!-- oc2:ask thread={state['thread_id']} seq={state['ask_seq']} -->"
    gh = await runtime.context.github(permissions={"issues": "write"})
    c = await gh.find_comment_with(state["repo"], state["issue_number"], marker)      # read-before-write
    if c is None:
        c = await gh.create_issue_comment(..., body=render_question(state["block"]) + "\n" + marker)
    return {"ask_posted_at": c.created_at}   # the comment's own timestamp, not now(): a re-run after a crash
                                             # must not move the sensor's `since=` past replies already made

def s10_wait(state):                     # nothing before interrupt(): resume re-runs only this
    decision = interrupt({"kind": "human", "seq": state["ask_seq"], "question": state["block"]},
                         response_schema=HumanDecision)
    return {"human_decision": decision.model_dump(), "ask_seq": state["ask_seq"] + 1,
            "human_asks": state["human_asks"] + 1}
```
Router after `S10_wait`: `answer` → back to the step that asked (`state["block"]["return_to"]`, e.g. S1 to re-gate the
edited issue, S3 with the answer as extra instructions); `retry` → same step with its counter reset by one;
`approve_protected_paths` → S5; `abort` / `human_asks > MAX_ASKS` → `S10_blocked`. **inferred**.

`S10_blocked(reason)` is terminal: post a comment + `oc2:blocked` label (idempotent by marker), keep the draft PR, `END`.
A later human command can start a **new** thread for the same issue (new `thread_id` suffix) that reuses the branch. **inferred**.

### 7.3 Delivering the question and receiving the answer
- **GitHub issue/PR comment (recommended first channel).** Question posted by `S10_ask`. A small **sensor** (the same
  process loop or launchd tick that supervises runs; see `04-durability-and-packaging.md` §2.3) polls
  `GET /repos/{o}/{r}/issues/{n}/comments?since=<ask_posted_at>` ("Only show results that were last updated after
  the given time") for each waiting thread, accepts only comments from allowed logins **and** with
  `author_association ∈ {OWNER, MEMBER, COLLABORATOR}` (values include `COLLABORATOR, CONTRIBUTOR, FIRST_TIMER,
  FIRST_TIME_CONTRIBUTOR, MANNEQUIN, MEMBER, NONE, OWNER`), or checks
  `GET /repos/{o}/{r}/collaborators/{login}/permission` like OpenHands' label policy, parses a strict command syntax
  (`/oc2 answer …`, `/oc2 retry`, `/oc2 abort`), and resumes with `Command(resume=HumanDecision(...).model_dump())`.
  **verified** API facts ([issue comments](https://docs.github.com/en/rest/issues/comments?apiVersion=2022-11-28#list-issue-comments),
  [OpenHands policy workflow](https://github.com/OpenHands/OpenHands/blob/b5d6b2ff2c90b3bb2a21a35cd396b61d88990831/.github/workflows/issue-readiness-check.yml)); flow **inferred**.
  Treat the comment body as untrusted text: it becomes *data* for the builder, never a command to the runner beyond the
  parsed verb. Edited comments (`updated_at` changes) must not re-resume: dedupe by comment id in the registry.
- **CLI** for the developer Mac: `oc2-flow pending` lists threads with `get_state(...).interrupts`;
  `oc2-flow answer <thread> --action retry --text "..."` resumes. Same resume code as the sensor. **inferred**.
- **Chat / OpenClaw later**: the same `Command(resume=...)` call behind an OpenClaw automation or tool. **inferred**.
- **Thread identity:** `thread_id = f"{owner}/{repo}#{issue}:{attempt}"` in a small registry table
  (`thread_id, repo, issue, pr_number, branch, status, waiting_kind, ask_seq, last_comment_id`). The PR body marker
  `<!-- oc2:thread=… -->` lets a PR comment be routed to the right thread. **inferred**.
- Agent Server alternative (threads have status `interrupted`; resume creates a new run) — see `04-durability-and-packaging.md` §2.1.

### 7.4 Other HITL examples
1. LangGraph docs approve/reject and review-and-edit patterns (`Command(resume=True|False)`), multiple-interrupt
   resume maps — [interrupts.md](https://docs.langchain.com/oss/python/langgraph/interrupts.md). **verified**.
2. Open SWE v1 planner `interrupt-proposed-plan` (accept/edit/reject; an `open-swe-auto` label auto-accepts) — `01-complete-workflows.md`. **verified via sibling**.
3. `langchain-ai/agent-inbox` (1.1k★, MIT) was the reference UI for interrupts but is **archived** (pushed 2026-09-18,
   `archived: true`); `langchain-ai/agent-chat-ui` (3.2k★, MIT, active) remains. **verified** (`gh api`). Do not build on agent-inbox.

---
## 8. Graph sketch (StateGraph, LangGraph ≥ 1.2.12) — **inferred design** built from the verified pieces above

### 8.1 Shape
```mermaid
flowchart TD
  START --> S1[S1_intake]
  S1 -->|ok| S2[S2_workspace]
  S1 -->|incomplete| ASK[S10_ask]
  S1 -->|rejected| BLK[S10_blocked]
  S2 --> S3[S3_build  subgraph/agent]
  S3 -->|done| S4[S4_local_gate]
  S3 -->|needs human / invalid x N| ASK
  S4 -->|pass| S5[S5_publish]
  S4 -->|fail < N| S3
  S4 -->|protected paths| ASK
  S4 -->|same failure twice / N| BLK
  S5 -->|pushed| S6[S6_ci_wait]
  S5 -->|no changes| S3
  S5 -->|lease rejected| ASK
  S6 -->|success| S7[S7_review  subgraph/agent]
  S6 -->|failure| S6L[S6_fetch_failure_logs]
  S6 -->|blocked, rerun budget| S6R[S6_rerun_failed]
  S6 -->|pending after drain| S6
  S6 -->|missing / timeout / conflict / head_moved| ASK
  S6R --> S6
  S6L -->|ci_failures < N, new fingerprint| S3
  S6L -->|else| BLK
  S7 --> S8{S8 route_after_review}
  S8 -->|approve| S9[S9_merge_ready]
  S8 -->|request_changes, round < N| S3
  S8 -->|2nd strike / no progress / blocked| ASK
  S8 -->|rounds exhausted| BLK
  S9 -->|ready| END
  S9 -->|head moved / conflict / mergeable unknown too long| ASK
  ASK --> WAIT[S10_wait  interrupt]
  WAIT -->|answer/retry| RET((return_to))
  WAIT -->|abort / asks > N| BLK
  BLK --> END
```
(`S8` is a router function on the edge out of `S7`, not a node. `RET` = route to `state.block.return_to`.)

### 8.2 State schema (JSON-primitive; secrets and clients only in `context`)
```python
from typing import Annotated, Literal, NotRequired, TypedDict
import operator

class IssueSnapshot(TypedDict):
    url: str; title: str; body: str; labels: list[str]; updated_at: str

class Workspace(TypedDict):
    task_dir: str; repo_dir: str; branch: str; base_ref: str; base_sha: str
    container: str; image: str

class BuildInput(TypedDict):          # what S3 gets this attempt
    reason: Literal["initial", "local_gate", "ci", "review", "human"]
    details: str                      # trimmed log / human answer
    open_findings: list[dict]         # Finding dicts (§6.3) when reason == "review"

class BuildResult(TypedDict):         # validated Pydantic at the S3 boundary
    status: Literal["done", "needs_human", "gave_up"]
    summary: str
    dispositions: list[dict]          # Disposition dicts (§6.3), one per open finding
    question: NotRequired[str]

class GateResult(TypedDict):
    passed: bool; failed_commands: list[str]; log_tail: str
    fingerprint: str | None; policy_violations: list[str]; artifact_path: str

class CiFailureReport(TypedDict):
    head_sha: str; fingerprint: str
    jobs: list[dict]                  # {workflow, job, step, url, excerpt, artifact_path}

class BlockInfo(TypedDict):
    kind: Literal["intake", "build", "gate_policy", "publish", "ci", "review", "error"]
    reason: str; question: str; return_to: str

class Event(TypedDict):               # tiny append-only audit trail; full logs live in artifacts/
    at: str; node: str; summary: str

class PipelineState(TypedDict, total=False):
    # identity / S1
    thread_id: str; repo: str; issue_number: int
    issue: IssueSnapshot; acceptance_criteria: list[str]
    intake_status: Literal["ok", "incomplete", "rejected"]
    started_at: float
    # S2
    workspace: Workspace
    # S3 / S4
    build_input: BuildInput; build_result: BuildResult; build_attempts: int
    local_gate: GateResult; local_gate_failures: int; last_gate_fingerprint: str | None
    # S5
    head_sha: str | None; last_pushed_sha: str | None
    pr_number: int | None; pr_node_id: str | None; pushed_at: float | None
    publish_status: Literal["pushed", "no_changes", "lease_rejected"]
    # S6
    ci_status: Literal["pending", "success", "failure", "blocked", "missing",
                       "conflict", "head_moved", "timeout"] | None
    ci_jobs: list[dict]; ci_failure_report: CiFailureReport | None
    ci_failures: int; ci_reruns: dict[str, int]; ci_fingerprints: list[str]
    # S7 / S8
    review: dict | None               # ReviewVerdict (§6.3)
    review_round: int
    findings_ledger: dict[str, dict]  # finding_id -> {finding, dispositions[], strikes}
    diff_hashes: list[str]
    # S9 / S10 / outcome
    block: BlockInfo | None; ask_seq: int; ask_posted_at: str | None
    human_asks: int; human_decision: dict | None
    outcome: Literal["merge_ready", "blocked"] | None
    events: Annotated[list[Event], operator.add]

@dataclass(frozen=True)
class Ctx:                            # runtime context: never checkpointed
    github: Callable[..., Awaitable["GitHub"]]   # mints a scoped App installation token per call (§2.2)
    docker: "DockerClient"
    required_checks: frozenset[tuple[str, str]]  # {("CI","lint"), ("CI","validate"), ("CI","unit")}
    gate_commands: tuple[str, ...]
    protected_paths: tuple[str, ...]
    limits: "Limits"                  # max_build_attempts=6, max_local_gate_failures=3, max_ci_failures=3,
                                      # max_ci_reruns_per_sha=1, max_review_rounds=3, max_human_asks=3,
                                      # ci_start_grace_s=600, ci_deadline_s=5400, thread_budget_s=8*3600
```

### 8.3 Routers (pure functions; unit-test each)
```python
def route_after_intake(s: PipelineState) -> str:
    return {"ok": "S2_workspace", "incomplete": "S10_ask"}.get(s["intake_status"], "S10_blocked")

def route_after_build(s, rt: Runtime[Ctx]) -> str:
    L = rt.context.limits
    if s["build_attempts"] > L.max_build_attempts or over_budget(s, L):  return "S10_blocked"
    return {"done": "S4_local_gate", "needs_human": "S10_ask"}.get(s["build_result"]["status"], "S10_blocked")

def route_after_gate(s, rt) -> str:
    g, L = s["local_gate"], rt.context.limits
    if g["policy_violations"]:                                          return "S10_ask"
    if g["passed"]:                                                     return "S5_publish"
    if g["fingerprint"] == s.get("last_gate_fingerprint"):              return "S10_blocked"   # no progress
    return "S3_build" if s["local_gate_failures"] < L.max_local_gate_failures else "S10_blocked"

def route_after_publish(s) -> str:
    return {"pushed": "S6_ci_wait", "no_changes": "S3_build"}.get(s["publish_status"], "S10_ask")

def route_after_ci(s, rt) -> str:
    st, L = s["ci_status"], rt.context.limits
    if st == "success":   return "S7_review"
    if st == "failure":   return "S6_fetch_failure_logs"
    if st == "pending":   return "S6_ci_wait"                             # only after a drain request
    if st == "blocked" and s["ci_reruns"].get(s["head_sha"], 0) < L.max_ci_reruns_per_sha:
        return "S6_rerun_failed"
    return "S10_ask"                                                    # missing | timeout | conflict | head_moved | blocked

def route_after_ci_logs(s, rt) -> str:
    rep, L = s["ci_failure_report"], rt.context.limits
    repeated = rep["fingerprint"] in s["ci_fingerprints"][:-1]
    return "S3_build" if s["ci_failures"] < L.max_ci_failures and not repeated else "S10_blocked"

def route_after_review(s, rt) -> str:                                  # this is S8
    ...  # rules 1-6 in §6.3

def route_after_human(s) -> str:
    d = s["human_decision"]["action"]
    if d == "abort" or s["human_asks"] > MAX_ASKS:                      return "S10_blocked"
    if d == "approve_protected_paths":                                  return "S5_publish"
    return s["block"]["return_to"]                                      # answer / retry
```

### 8.4 Wiring
```python
DET = dict(retry_policy=RetryPolicy(max_attempts=4, initial_interval=2.0, retry_on=is_transient))  # 5xx/429/network only

def to_human(state, error: NodeError) -> Command[Literal["S10_ask"]]:   # default error handler (langgraph>=1.2)
    return Command(goto="S10_ask", update={"block": {
        "kind": "error", "reason": f"{error.node}: {type(error.error).__name__}: {str(error.error)[:300]}",
        "question": "A step failed after retries. Reply `/oc2 retry` or `/oc2 abort`.", "return_to": error.node}})

g = StateGraph(PipelineState, context_schema=Ctx).set_node_defaults(error_handler=to_human)
g.add_node("S1_intake", s1_intake, timeout=60, **DET)
g.add_node("S2_workspace", s2_workspace, timeout=15 * 60, **DET)
g.add_node("S3_build", s3_build)                      # wraps builder agent subgraph/harness (02-*.md); own budgets
g.add_node("S4_local_gate", s4_local_gate, timeout=30 * 60)
g.add_node("S5_publish", s5_publish, timeout=10 * 60, **DET)   # commit/push/open_pr as @task inside
g.add_node("S6_ci_wait", s6_ci_wait, timeout=TimeoutPolicy(run_timeout=95 * 60, idle_timeout=300, refresh_on="heartbeat"), **DET)
g.add_node("S6_fetch_failure_logs", s6_fetch_failure_logs, timeout=5 * 60, **DET)
g.add_node("S6_rerun_failed", s6_rerun_failed, timeout=60, **DET)
g.add_node("S7_review", s7_review)                    # wraps reviewer agent; returns ReviewVerdict for head_sha
g.add_node("S9_merge_ready", s9_merge_ready, timeout=10 * 60, **DET)
# S10 nodes must not route their own failures back to S10_ask (that would loop): if posting the question fails,
# still pause (the CLI lists pending interrupts); if the final "blocked" comment fails, just end.
g.add_node("S10_ask", s10_ask, timeout=60, **DET, error_handler=lambda s: Command(goto="S10_wait"))
g.add_node("S10_wait", s10_wait)                      # interrupt() only
g.add_node("S10_blocked", s10_blocked, timeout=60, **DET, error_handler=lambda s: Command(goto=END))

g.add_edge(START, "S1_intake")
g.add_conditional_edges("S1_intake", route_after_intake, ["S2_workspace", "S10_ask", "S10_blocked"])
g.add_edge("S2_workspace", "S3_build")
g.add_conditional_edges("S3_build", route_after_build, ["S4_local_gate", "S10_ask", "S10_blocked"])
g.add_conditional_edges("S4_local_gate", route_after_gate, ["S5_publish", "S3_build", "S10_ask", "S10_blocked"])
g.add_conditional_edges("S5_publish", route_after_publish, ["S6_ci_wait", "S3_build", "S10_ask"])
g.add_conditional_edges("S6_ci_wait", route_after_ci,
                        ["S7_review", "S6_fetch_failure_logs", "S6_ci_wait", "S6_rerun_failed", "S10_ask"])
g.add_edge("S6_rerun_failed", "S6_ci_wait")
g.add_conditional_edges("S6_fetch_failure_logs", route_after_ci_logs, ["S3_build", "S10_blocked"])
g.add_conditional_edges("S7_review", route_after_review, ["S9_merge_ready", "S3_build", "S7_review", "S10_ask", "S10_blocked"])
g.add_conditional_edges("S9_merge_ready", route_after_merge_ready, [END, "S10_ask"])
g.add_edge("S10_ask", "S10_wait")
ALL_NODES = [n for n in g.nodes]                      # error handler may set return_to = any failed node
g.add_conditional_edges("S10_wait", route_after_human, ALL_NODES)
g.add_edge("S10_blocked", END)

async with AsyncSqliteSaver.from_conn_string(str(Path.home() / ".oc2/state/checkpoints.sqlite")) as saver:
    graph = g.compile(checkpointer=saver)             # from_conn_string is an async context manager
```
Counters are incremented by the node that owns them (`S3_build` → `build_attempts`, `S4` → `local_gate_failures`,
`S6_fetch_failure_logs` → `ci_failures` + `ci_fingerprints`, `S7_review` → `review_round` + ledger, `S10_wait` →
`human_asks`), so routers stay pure. **inferred**.

### 8.5 Driver (one thread per issue; crash-resume; interrupt-aware)
```python
async def drive(repo: str, issue: int, ctx: Ctx, control: RunControl) -> None:
    cfg = {"configurable": {"thread_id": f"{repo}#{issue}:1"}, "recursion_limit": 150}
    snap = await graph.aget_state(cfg)
    if snap.interrupts:                         # waiting for a human: the sensor resumes it
        return
    if snap.values and not snap.next:           # already finished (merge_ready or blocked): never restart in place
        return
    inp = None if snap.next else {"repo": repo, "issue_number": issue, "started_at": time.time(),
                                  "build_attempts": 0, "local_gate_failures": 0, "ci_failures": 0,
                                  "ci_reruns": {}, "ci_fingerprints": [], "review_round": 0,
                                  "ask_seq": 0, "human_asks": 0, "events": []}
    out = await graph.ainvoke(inp, cfg, context=ctx, durability="sync", control=control, version="v2")
    registry.record(cfg, out.interrupts, out.value.get("outcome"))
# sensor tick: for each waiting thread → read new issue/PR comments → graph.ainvoke(Command(resume=...), cfg, context=ctx, ...)
```
`snap.next` non-empty without interrupts = the process died or drained mid-run → `invoke(None, cfg)` resumes from the
last checkpoint (**verified** resume form, fault-tolerance.md "Resume after drain"; crash case per checkpointers.md
"Pending writes"). Exact `aget_state` field use is **inferred** from the `StateSnapshot` definition (§7.1).

---
## 9. Recommendations, cross-cutting notes, open questions

### 9.1 Recommendations (one line each)
1. **Graph:** StateGraph for S1–S10; plain dict updates from nodes; routing in pure `route_after_*` functions
   (unit-tested); `Command` only in the default error handler; `@task` around each external effect inside S5.
2. **LangGraph ≥ 1.2.12 features to use:** async nodes with `timeout=`/`TimeoutPolicy` (+`runtime.heartbeat()` in
   S6), `RetryPolicy(retry_on=<transient only>)` on every deterministic node (the default retries 4xx and
   `CalledProcessError`), `set_node_defaults(error_handler=…)` → `S10_ask`, `durability="sync"`, `RunControl` drain,
   `interrupt(…, response_schema=Model)`, `invoke(..., version="v2")`.
3. **Loops:** named counters in state checked by routers + an explicit `recursion_limit` (~150) backstop; the
   recursion limit is per invocation (resets on every resume) and its default is huge (docs 1000, code 10007).
4. **GitHub:** githubkit (async, typed, REST+GraphQL) with a dedicated GitHub App and one repo-scoped,
   least-permission installation token per node; `gh` for humans; fine-grained PAT only for a spike (then use the
   Actions API — PATs cannot get `checks:read`).
5. **Git/workspace:** plain `git` CLI; bare mirror + `git clone --local` per task; one container per task via
   docker-py, work tree RW, `.git` RO, no credentials inside; task dirs under `$HOME` because this Mac uses Colima.
6. **S4:** commands from config, fresh no-network container, diff policy (protected paths, empty diff, size) before
   tests; for openclaw2-deploy S4 cannot mirror CI on Apple Silicon (`ops/ci.sh` requires Linux/x86_64), so S6 is
   authoritative.
7. **S6:** in-node async polling keyed on the pushed `head_sha`, required checks keyed by **(workflow, job)** from
   config (this repo has no GitHub-required checks and duplicate `validate` names), pure `classify()`, grace for
   "no checks yet", deadline, conflict/head-moved detection, per-job log fetch + trim, ≤ 1 infra re-run per SHA.
8. **S8:** verdict bound to `head_sha`; findings ledger with stable ids and `fixed|declined|deferred` dispositions;
   3 rounds max; two-strike and no-progress rules → S10; never defer a blocker.
9. **S10:** `S10_ask` (idempotent comment with marker) → `S10_wait` (`interrupt` only); a sensor resumes threads from
   authorised `/oc2 …` replies (and a CLI does the same); `S10_blocked` is terminal and leaves the draft PR.
10. **S9:** re-verify head/mergeability/required checks via GraphQL, `markPullRequestReadyForReview` if draft,
    one summary comment + label, `END`; never merge (no merge call exists anywhere in the graph or its tokens:
    S9's token gets `pull_requests:write` but the code never calls a merge endpoint — enforce with a unit test that
    greps for `merge` mutations/endpoints).

### 9.2 Cross-cutting (X) items from this area
- **Checkpoint/resume:** AsyncSqliteSaver file outside every container mount; `LANGGRAPH_STRICT_MSGPACK=true`; state
  JSON-primitive; resume crashed threads with `invoke(None, cfg)`; S5/S9/S10_ask idempotent by read-before-write.
- **Budgets/stuck detection:** per-node timeouts; per-thread wall-clock budget (`started_at` + `thread_budget_s`) in
  every router; failure fingerprints (gate, CI, findings, diff hash) to catch "same failure again" and A→B→A loops.
- **Secret isolation:** tokens only in `Ctx` factories, minted per node, passed to git through `GIT_CONFIG_*` env
  for one process; host git never runs with agent-writable config/hooks.
- **Observability without third parties:** LangSmith tracing is opt-in (`export LANGSMITH_TRACING=true`;
  "This will NOT be traced (if LANGSMITH_TRACING is not set)") — **verified**, [observability.md](https://docs.langchain.com/oss/python/langgraph/observability.md).
  Locally: `stream_mode="updates"` → JSONL per thread in `artifacts/`, plus the small `events` list in state.
  Details in `04-durability-and-packaging.md`.

### 9.3 Open questions for Alex
1. Add a ruleset that makes `CI/lint`, `CI/validate`, `CI/unit` required on `main`? It would let GitHub (`isRequired`,
   `gh pr checks --required`, `mergeStateStatus`) agree with the workflow's own predicate. Repo-settings change.
2. New dedicated GitHub App for the prototype, or reuse the existing OpenClaw App? (Least privilege argues for new.)
3. Human channel for S10: GitHub issue/PR comments first (proposed), OpenClaw chat later?
4. S4 for openclaw2-deploy: skip, run a reduced Python-only unit subset, or run an amd64 Colima profile (slow)?
5. Who may answer S10 questions — only `bodegus`, or any `OWNER/MEMBER/COLLABORATOR`?

### 9.4 Small experiments worth running before building (each < 30 min)
1. Colima: RW work-tree bind + RO `.git` overlay — `git status`/`git diff` work in the container, `git commit` and
   hook/config writes fail.
2. Async S6-style node with `TimeoutPolicy(idle_timeout, refresh_on="heartbeat")`; `kill -9` the runner mid-poll;
   `invoke(None, cfg)` resumes in S6 without re-running S5.
3. `interrupt(response_schema=HumanDecision)` answered from a second process with `Command(resume=…)`; invalid
   answer is rejected and can be re-sent.
4. githubkit `as_installation(id, repositories=[repo], permissions={...})` token: create draft PR, then
   `markPullRequestReadyForReview` via `async_graphql`; confirm a 403 for anything outside the granted permissions.
5. githubkit HTTP cache: confirm repeated polls produce `304`s (rate-limit headers unchanged).
6. Builder as a subgraph called inside `S3_build`: `kill -9` mid-loop, resume, and confirm the agent loop continues
   from its own checkpoint instead of restarting (§1.4 claim is **inferred**).

### 9.5 Gaps / weak evidence
- I found **no** well-known open-source LangGraph `StateGraph` with a CI-wait **node**; the strongest real example
  (Open SWE `/baby-sit`) uses Agent Server crons + webhooks around agent runs rather than a node inside one graph.
  GitHub code search (`"from langgraph" check_runs` / `workflow_runs`) otherwise returned only tiny repos (0–5★). **verified by search (weak)**.
- Nested RO mount behaviour under Colima, `git status` with a read-only index, and githubkit's ETag behaviour are
  **inferred** until the experiments above run.
