# 05 — Using the ChatGPT/Codex subscription (OAuth) from a LangGraph workflow

Research date: 2026-10-13. Status: COMPLETE (2026-10-13).
Legend: **verified** = read in a primary source (link given); **inferred** = my reasoning, not stated by a source.

## 0. Summary and recommendation

**Top findings (each verified in §1–§4 unless marked)**
1. **`codex mcp-server` is gone** (removed 2026-09-05, openai/codex#42993), and `langchain-mcp-adapters` is archived. The MCP route is dead.
2. **There is an official Python Codex SDK**, `openai-codex` (stable, released with every CLI build; 0.162.1 on 2026-10-09). It drives `codex app-server` over stdio and covers threads, turns, `output_schema`, `thread_resume`, interrupt, streaming, `ExternalMessage` for untrusted input, and browser, device-code or API-key login. It is the cleanest way to put the Codex agent inside a LangGraph node.
3. **OpenAI launched a sanctioned way to spend a ChatGPT plan from third-party local apps** on 2026-09-29: "Sign in with ChatGPT" plan usage. It uses dynamic client registration, loopback OAuth with scope `chatgpt.tokens.use.direct`, and `POST https://api.openai.com/v1/responses`; it works with the stock OpenAI SDK and has per-app weekly caps. It is in preview: 1-hour access tokens, rotating 30-day refresh tokens, no device code, no quota API, many request parameters unsupported. OpenAI even documents running `codex app-server` on these tokens through a custom provider.
4. **Codex-managed ChatGPT auth in unattended automation is documented by OpenAI** for trusted private automation: one `auth.json` per runner or serialised stream, never shared across machines, never on public repos. Refresh tokens rotate; refresh happens 5 minutes before expiry or after 8 days; reuse is caught as `refresh_token_reused`; there is no cross-process file lock, but the server allows a short reuse window.
5. **Every login on the account shares one plan allowance** (5-hour and weekly windows on Plus, weekly on Pro), so the workflow competes with Alex's interactive Codex. App-server exposes `account/rateLimits/read`, which a budget guard can poll.
6. **Third-party proxies that reuse the Codex CLI client ID** (LiteLLM `chatgpt/`, ChatMock, openai-oauth, CLIProxyAPI, langchain-codex-oauth) work, but they impersonate the first-party client against an undocumented endpoint and have open correctness bugs. With SIWC available they are the wrong foundation.
7. **Codex's sandbox does not stop the agent reading `auth.json` by default.** A deny-read permission profile works under macOS Seatbelt; in Linux containers it depends on bubblewrap, which usually fails in Docker, and the Landlock fallback ignores read denies (#11316). Real isolation needs a process split: an `exec-server` remote environment (experimental) or a SIWC token broker.

**Recommendation**
- **Primary: the Codex agent as the builder/reviewer harness through the official Python SDK (`openai-codex`, pinned), on a dedicated workflow Codex login.** Create it once with `codex login --device-auth` (or on the Mac) into its own `CODEX_HOME`, use file storage, and run one long-lived app-server per `CODEX_HOME`. Set `approval_mode=deny_all`; builder threads use `workspace_write`, reviewer threads `read_only` or built-in `review/start`. Persist thread IDs in LangGraph state. Keep GitHub credentials only in the deterministic nodes and out of the SDK's inherited environment. Phase 1 runs natively on macOS under Seatbelt with a deny-read rule on the workflow `CODEX_HOME`. Phase 2 moves tool execution into a per-task container through `codex exec-server` (spike first).
- **Fallback: the same harness on an OpenAI API key** (`login_api_key` / `CODEX_API_KEY`, optionally behind `codex responses-api-proxy` for isolation). Switching is a config change with no code change, and it is the documented CI recommendation.
- **Spike in parallel (likely future primary for auth): SIWC plan-usage tokens feeding the same Codex harness** through the documented custom provider. The refresh token stays in the host process, there is a per-app cap, and it is explicitly within the SIWC Terms for authorised automation. Promote it once a test shows tool calls, `output_schema` and token refresh work, with no hourly restart if `model_providers.<id>.auth.command` behaves.
- **Do not use**: `codex mcp-server` (removed), the `chatgptAuthTokens` login (marked OpenAI-internal), Codex-client-ID proxies, multi-account pooling, or copying Alex's own `~/.codex/auth.json`.

**Open questions / spikes**
1. Does `environments.toml` with `include_local=false` route *all* tool activity (shell, `apply_patch`, file reads, MCP) into the remote exec-server? Canary test: the agent tries to read the workflow `auth.json`.
2. SIWC + Codex app-server: does Codex avoid `tool_search` by default; does `auth.command` refresh work without a restart; do `output_schema` and parallel tool calls work under the preview limits?
3. Do SIWC Terms count a GitHub-issue-triggered, unattended run as an expressly authorised automation? Probably yes when Alex both creates and labels the issue. Not confirmed by OpenAI.
4. Which plan does Alex have? On Plus the 5-hour window makes a long build plus review loop likely to collide with interactive use; budget thresholds should be set per plan.
5. Rate-limit windows are not available for SIWC tokens (openai/sign-in-with-chatgpt-devkit#3), so the budget guard must count turns and tokens itself in that mode.

**Untested sketch of the S3 node (inferred API usage)**
```python
from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, ExternalMessage, Sandbox  # all exported (sdk/python/src/openai_codex/__init__.py)

# One app-server per call is fine for one task at a time. For concurrent tasks, share one long-lived
# AsyncCodex per CODEX_HOME (no cross-process refresh lock, see 1.3) instead of opening one per node.
async def build(state):
    cfg = CodexConfig(env={"CODEX_HOME": WORKFLOW_CODEX_HOME}, cwd=state["worktree"])
    async with AsyncCodex(cfg) as codex:
        if state.get("builder_thread"):
            thread = await codex.thread_resume(state["builder_thread"])
        else:
            thread = await codex.thread_start(sandbox=Sandbox.workspace_write,
                                              approval_mode=ApprovalMode.deny_all,
                                              developer_instructions=BUILDER_RULES)
        msg = ExternalMessage(tool_name="workflow", namespace="ci", content=state["feedback"]) \
              if state.get("feedback") else state["task_prompt"]
        result = await thread.run(msg, output_schema=DONE_SCHEMA)
    return {"builder_thread": thread.id, "build_result": result.final_response,
            "usage": result.usage}
```

## 1. How Codex CLI auth works today

Pinned source: `openai/codex` tag **rust-v0.162.1** (latest stable, published 2026-10-09; repo 128,969 stars, Apache-2.0, last push 2026-10-13, actively maintained — several releases per week).
Permalink base used below: `https://github.com/openai/codex/blob/rust-v0.162.1/` (abbreviated `codex@0.162.1/`).
Official docs moved: `developers.openai.com/codex/*` now 308-redirects to `learn.chatgpt.com/docs/*` (observed 2026-10-13).

### 1.1 Login flows (verified)
| Flow | Command | Mechanics | Source |
|---|---|---|---|
| Browser (PKCE) | `codex login` | Local callback server on `127.0.0.1:1455` (`/auth/callback`), issuer `https://auth.openai.com`, `GET /oauth/authorize` with scope `openid profile email offline_access api.connectors.read api.connectors.invoke`, extra params `codex_cli_simplified_flow=true`, `originator=…`; code exchanged at `/oauth/token`. After sign-in it also tries an RFC 8693 token-exchange (`requested_token=openai-api-key`) and stores the result as `OPENAI_API_KEY` if it succeeds. | `codex@0.162.1/codex-rs/login/src/server.rs` L77-78, L194, L586-617, L1023-1045 |
| Device code (beta) | `codex login --device-auth` | `POST {issuer}/api/accounts/deviceauth/usercode` → user opens `https://auth.openai.com/codex/device` and types the one-time code (expires 15 min) → CLI polls `/api/accounts/deviceauth/token` → receives an authorization code + PKCE verifier → normal `/oauth/token` exchange. Docs say device-code login must first be enabled in ChatGPT security settings. | `codex-rs/login/src/device_code_auth.rs` L60-200; docs https://learn.chatgpt.com/docs/auth |
| SSH port-forward | forward `localhost:1455` | Use the browser flow from a remote host. | https://learn.chatgpt.com/docs/auth |
| Copy auth cache | copy `~/.codex/auth.json` | Officially documented fallback for headless machines; the docs say to protect the file like a password. | https://learn.chatgpt.com/docs/auth |
| API key | `printenv OPENAI_API_KEY \| codex login --with-api-key` | Stored as `OPENAI_API_KEY` in auth.json; billed at API rates. `--api-key <value>` is deprecated. `CODEX_API_KEY` env var overrides everything (only honoured where the caller enables it, e.g. `codex exec`). | `codex-rs/cli/src/main.rs` L516-556; `codex-rs/login/src/auth/manager.rs` L953-970, L1500-1506 |
| Codex access token | `printenv CODEX_ACCESS_TOKEN \| codex login --with-access-token` or env `CODEX_ACCESS_TOKEN` | Tokens prefixed `at-` are validated against `https://auth.openai.com/api/accounts/v1/user-auth-credential/whoami`; other values are treated as an Agent Identity JWT. **Only for ChatGPT Business and Enterprise workspaces** (admin console, finite 1–90-day expiry). Not available on Plus/Pro. | `codex-rs/login/src/auth/access_token.rs` L1-12; `auth/personal_access_token.rs` L11-13; docs https://learn.chatgpt.com/docs/enterprise/access-tokens |

The OAuth client ID is the public Codex CLI client `app_EMoamEEZ73f0CkXaXp7hrann` (`auth/manager.rs` L1718); env overrides exist for issuer/client/refresh URL (`CODEX_APP_SERVER_LOGIN_CLIENT_ID`, `CODEX_REFRESH_TOKEN_URL_OVERRIDE`) — test hooks, not something to use.

### 1.2 Where credentials live (verified)
- `CODEX_HOME` env var, default `~/.codex`; if set it **must already exist** and be a directory (`codex-rs/utils/home-dir/src/lib.rs` L13-50).
- `cli_auth_credentials_store = "file" | "keyring" | "auto" | "ephemeral"`; **default `file`** (`codex-rs/config/src/types.rs` L133-146). Keyring service name `Codex Auth`, key `cli|<first 16 hex of sha256(canonical CODEX_HOME)>` (`auth/storage.rs` L243-258), so two CODEX_HOMEs on one Mac get two independent keychain entries.
- `$CODEX_HOME/auth.json` is written with mode `0600` via truncate-and-write (no temp-file rename, no file lock) (`auth/storage.rs` L214-231).
- Shape (`AuthDotJson`, `auth/storage.rs` L47-73; `token_data.rs` L10-40): `auth_mode`, `OPENAI_API_KEY`, `tokens { id_token, access_token, refresh_token, account_id }`, `last_refresh`, plus optional `agent_identity`, `personal_access_token`, Bedrock fields. `id_token` claims carry email, `chatgpt_plan_type`, `chatgpt_user_id`, `chatgpt_account_id`.
- Precedence when loading (`auth/manager.rs` `load_auth` L1489-1590): `CODEX_API_KEY` (if enabled) → in-memory "external" ChatGPT tokens → `CODEX_ACCESS_TOKEN` → persisted store (file/keyring/auto).

### 1.3 Refresh and rotation (verified)
- Proactive refresh when the access-token JWT expires within **5 minutes**, or when `last_refresh` is older than **8 days** (`auth/manager.rs` L203-204, L3001-3023). Also on HTTP 401 (unauthorized-recovery path).
- Refresh = `POST https://auth.openai.com/oauth/token` (JSON body, `client_id` + `refresh_token`); response may return new `id_token`, `access_token` **and a new `refresh_token`**, which is persisted with a new `last_refresh` (`persist_tokens` L1600-1625, `request_chatgpt_token_refresh` L1627-1678). I.e. refresh tokens rotate.
- Permanent failures are classified from the server error code: `refresh_token_expired`, `refresh_token_reused` (message: the refresh token was already used, log in again), `refresh_token_invalidated` (revoked) (L206-211, L1680-1712). Permanent failure = human must re-login.
- Before refreshing, `AuthManager::refresh_token()` re-reads storage; if another process already wrote new tokens it uses them instead of refreshing again (`auth/manager.rs` L2840-2878). Inside one process a semaphore serialises refreshes. **Across processes there is no lock.** An OpenAI maintainer said the server accepts a refresh token more than once within a short grace window (about an hour) before invalidating it, which softens this race (openai/codex#10332, closed 2026-02-02). Users still report `refresh_token_reused` loops (openai/codex#19803, open; #39199, open, Windows with two web accounts). So sharing one `CODEX_HOME` between concurrent processes is survivable but not clean. (verified: code + maintainer comment)
- `codex logout` revokes tokens at `https://auth.openai.com/oauth/revoke` before deleting them (`auth/manager.rs` L994-1020, L213).

### 1.4 Sharing one login vs. separate logins
- **Official rule** (CI/CD guide, https://learn.chatgpt.com/docs/auth/ci-cd-auth, formerly developers.openai.com/codex/auth/ci-cd-auth): use one `auth.json` per runner or per serialised workflow stream; do not share one file across concurrent jobs or several machines; do not overwrite a refreshed file with the original seed. If another machine or job rotated the token first, refresh stops working and you must log in again. (verified)
- **Two processes on one machine sharing one `CODEX_HOME`**: works most of the time because of the reload-before-refresh check and the server's reuse grace window, but there is no file lock. Safer: one long-lived Codex process (app-server) per `CODEX_HOME`, or serialise. (verified code; recommendation inferred)
- **Copying one login to two machines/containers**: unsupported — the first refresh on one copy invalidates the other copy's refresh token (`refresh_token_reused`). (verified by doc + error code)
- **Two independent logins on one ChatGPT account** (e.g. Mac `~/.codex` plus a container `CODEX_HOME`, each from its own `codex login`/`--device-auth`): each login is a separate OAuth grant with its own refresh-token chain, so they do not invalidate each other. The Codex CI guide's one-seeded-file-per-runner model implies one independent login per runner. For SIWC the docs say it outright: one issued `client_id` may be reused on several agent hosts for the same user and workspace, provided each host has its own `ext_agent_host_id` (https://developers.openai.com/siwc/token-sharing-open-source). I found no doc that caps the number of concurrent logins. (Codex: inferred; SIWC: verified)
- **Usage limits belong to the plan, not to a login**: the pricing page says local messages and cloud chats share the plan's allowance. Plus and Standard Business have a 5-hour rolling window plus weekly limits; Pro currently has no 5-hour limit. A turn that hits the limit may finish, after which you need credits or an API key (https://learn.chatgpt.com/docs/pricing, fetched 2026-10-13; verified). The page has no per-login or per-device allowance, so a workflow login and Alex's interactive Codex use **draw from the same quota** (inferred, strongly implied). SIWC adds per-app weekly caps, but they cap one app's share; they do not add allowance (§2.2 B1).
- Rate-limit state is exposed to clients: app-server `account/rateLimits/read` returns `primary`/`secondary` windows (`used_percent`, `window_duration_mins`, `resets_at`), plus `account/rateLimits/updated` notifications (`codex-rs/app-server-protocol/src/protocol/v2/account.rs` L315-345, L650-760). Useful for the budget guard (X).

### 1.5 API-key mode as the fallback (verified)
`codex login --with-api-key`, or `CODEX_API_KEY=… codex exec …` for one run. Billed at API rates; docs recommend API keys for automation in shared environments like CI (https://learn.chatgpt.com/docs/pricing, https://learn.chatgpt.com/docs/non-interactive-mode). An API key also unlocks `codex-responses-api-proxy` (§4) and every standard LangChain/LiteLLM provider. Switching the same graph from subscription to API key is a config change, not a code change, if the agent harness is Codex.

## 2. Ways to spend the subscription from Python / LangGraph

### 2.0 The big change since our earlier assumptions (verified)
1. **`codex mcp-server` no longer exists.** Deprecated with a warning on 2026-08-20 (openai/codex#39657) and removed on 2026-09-05 (openai/codex#42993 deletes the subcommand and the standalone `codex-mcp-server` crate). Not present in rust-v0.162.1; the Codex SDK docs confirm the removal (https://learn.chatgpt.com/docs/codex-sdk). Any plan built on `codex mcp-server` + `langchain-mcp-adapters` is dead; `langchain-mcp-adapters` itself was archived (repo archived, README points to `langchain[mcp]` / `langchain.mcp`). Community MCP wrappers around `codex exec` exist but add nothing over calling the SDK directly.
2. **OpenAI now has an official, sanctioned way for third-party local apps to spend a ChatGPT plan**: "Sign in with ChatGPT" (SIWC) with *ChatGPT plan usage*, announced at DevDay on 2026-09-29 (TechCrunch, https://techcrunch.com/2026/09/29/openais-latest-features-take-direct-aim-at-the-app-store-model/). The developer docs say plan usage is for open-source and locally hosted apps; paid or remotely hosted apps must use an interest form (https://developers.openai.com/siwc/token-sharing-open-source). OpenClaw, OpenCode, Pi and T3 are listed open-source integrations (https://learn.chatgpt.com/docs/sign-in-with-chatgpt). Details in §2.2 B1.
3. **An official Python Codex SDK exists**: `openai-codex` on PyPI (first beta 2026-05-28; 0.162.1 on 2026-10-09; "Production/Stable"), a typed JSON-RPC client for `codex app-server` over stdio that pins a matching CLI binary (`openai-codex-cli-bin==0.162.1`) (https://github.com/openai/codex/tree/rust-v0.162.1/sdk/python, https://pypi.org/project/openai-codex/).

### 2.1 Option A — run the Codex agent itself as the builder/reviewer harness (official clients; auth = Codex login)

| Variant | Mechanics (verified) | Maturity | Fit |
|---|---|---|---|
| **A1. Python SDK `openai-codex`** (recommended) | `Codex(CodexConfig(env={"CODEX_HOME": ...}, cwd=...))` starts `codex app-server` (stdio) and calls `initialize`. `thread_start(sandbox=Sandbox.workspace_write, developer_instructions=…, model=…, config={...})`, `thread.run(input, output_schema=…, effort=…)` → `TurnResult(final_response, items, usage)`; `thread.turn(...)` gives a `TurnHandle` with `stream()`/`interrupt()`; `codex.thread_resume(thread_id)`; `codex.account()`; logins `login_chatgpt()`, `login_chatgpt_device_code()`, `login_api_key()`. `ExternalMessage` passes untrusted text (issue bodies, CI logs, review findings) with tool-level, not user-level, authority. Sources: `sdk/python/README.md`, `docs/getting-started.md`, `docs/api-reference.md` L58-115, L186-195, `src/openai_codex/client.py` L195-211 (`CodexConfig` fields `codex_bin, launch_args_override, config_overrides, cwd, env, …`). | Official, Apache-2.0, released with every stable CLI (5 releases 2026-10-01…10-09). Sync and async clients. | **Best fit.** A LangGraph node owns one `AsyncCodex` per task; persist Codex `thread_id` in LangGraph state so a restarted graph calls `thread_resume`. Rollouts live under `$CODEX_HOME/sessions` unless `ephemeral=True`. |
| **A2. `codex exec --json` subprocess** | Flags: `--json` (JSONL events `thread.started{thread_id}`, `turn.started`, `item.started/updated/completed`, `turn.completed{usage: input/cached/output/reasoning tokens}`, `turn.failed`, `error`), `--output-schema FILE`, `-o/--output-last-message FILE`, `--sandbox read-only\|workspace-write\|danger-full-access`, `--ephemeral`, `--skip-git-repo-check`, `--ignore-user-config`, `--ignore-rules`; resume with `codex exec resume <SESSION_ID>` or `--last`. `codex exec review --base BRANCH \| --commit SHA \| --uncommitted [PROMPT]` runs the built-in reviewer. `--full-auto` is now deprecated. Sources: `codex-rs/exec/src/cli.rs` L21-84, L187-233, L296-328; `codex-rs/exec/src/exec_events.rs` L13-72; https://learn.chatgpt.com/docs/non-interactive-mode. | Official, stable, most-documented automation path. | Good fallback when the SDK misbehaves: one process per step, no long-lived child. Crash recovery = re-run with `resume <thread_id>`. |
| **A3. Raw app-server JSON-RPC** | `codex app-server` (stdio default; the docs call the WebSocket transport experimental and not supported for production; ws auth via capability token or signed bearer). Methods include `thread/start`, `thread/resume`, `thread/fork`, `turn/start` (with `outputSchema`, `sandboxPolicy`), `turn/steer`, `review/start`, `account/read`, `account/login/start`, `account/rateLimits/read` (+ `account/rateLimits/updated`), `account/usage/read`, `environment/add` / `environment/info`. Schema generators: `codex app-server generate-ts`, `generate-json-schema`. Sources: https://learn.chatgpt.com/docs/app-server; `codex-rs/app-server-protocol/src/protocol/common.rs`. | Stdio API stable enough that both official SDKs sit on it; individual methods marked experimental. | Only if the Python SDK lacks something (e.g. `review/start`, rate limits). The SDK's `CodexClient` is the raw JSON-RPC client, so drop down rather than reimplement. |
| **A4. TypeScript SDK `@openai/codex-sdk`** | Spawns the CLI and exchanges JSONL over stdin/stdout; `startThread()`, `run()`, `runStreamed()`, per-turn JSON-schema output. npm 0.162.1 (2026-10-09), Apache-2.0. Source: `sdk/typescript/README.md`. | Official. | Not useful for a Python LangGraph except as a sidecar. |
| ~~A5. `codex mcp-server` + `langchain-mcp-adapters`~~ | Removed 2026-09-05 (see §2.0). | Dead. | Do not use. |

Built-in reviewer output is already structured: `ReviewOutputEvent { findings[{title, body, confidence_score, priority, code_location{absolute_file_path, line_range}}], overall_correctness, overall_explanation, overall_confidence_score }` (`codex-rs/protocol/src/protocol.rs` L3505-3545). That maps directly to S7's verdict and findings without a custom prompt, or you can pass our own `output_schema`.

Auth for Option A: whatever Codex is logged in with in that `CODEX_HOME` — ChatGPT login (`auth.json`), API key, or (Business/Enterprise) access token. Rate-limit and usage reads come for free through app-server (§1.4). Restriction: the `chatgptAuthTokens` login type, which would let *our* process hold the refresh token and hand Codex only access tokens, is marked unstable and for OpenAI internal use only, with an explicit do-not-use note (`codex-rs/app-server-protocol/src/protocol/v2/account.rs` L86-99). Do not build on it.

### 2.2 Option B — call the model directly from a LangChain chat model with a ChatGPT token

Two technically different routes exist. Only the first is sanctioned for third-party code.

#### B1. Official route: Sign in with ChatGPT (SIWC) plan usage → `api.openai.com/v1/responses` (verified unless marked)
- **Eligibility**: plan usage is offered to open-source and locally hosted apps; paid or remotely hosted apps go through an interest form (https://developers.openai.com/siwc/token-sharing-open-source). The cookbook phrases it as open-source projects, personal projects that run locally, and selected private apps (https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt). A personal LangGraph prototype on Alex's Mac fits the cookbook's local personal-project category (inferred from the wording; no explicit ruling on unattended automation found). User side: the help page names eligible Plus and Pro subscribers (https://learn.chatgpt.com/docs/sign-in-with-chatgpt).
- **Registration** (https://developers.openai.com/siwc/token-sharing-open-source/sign-in): no separate registration call. First sign-in uses `client_id=dynamic_agent_client` plus `agent_name_hint` and a per-installation `ext_agent_host_id` (`urn:uuid:…`, persisted); the real `client_id` is issued at the callback. Authorize at `https://auth.openai.com/api/accounts/authorize` with `response_type=code`, `redirect_uri=http://127.0.0.1:<port>/callback` (loopback only), scope `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`, `resource=https://api.openai.com/v1`, PKCE S256, `state`, `nonce`. Token endpoint `https://auth.openai.com/api/accounts/oauth/token` (form-encoded, public client). Persist `{client_id, ext_agent_host_id, id_token, access_token, refresh_token, scopes, …}` atomically with mode 0600.
- **Tokens** (https://developers.openai.com/siwc/token-sharing-open-source/token-reference): access token 1 h; refresh token 30 days and rotates on every use. The docs require serialising refreshes per session so two processes never race a rotating token, and forbid copying credentials between machines (https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions).
- **Inference** (https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference): `POST https://api.openai.com/v1/responses` with `Authorization: Bearer <access_token>`, `store:false`, `stream:true`; list models with `GET /v1/models` (`visibility=="list"`). The stock OpenAI Python SDK works with `api_key=<access token>`.
- **Preview limits** (https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations): function/custom tools supported; not supported: `background`, `conversation`, `max_output_tokens`, `max_tool_calls`, `metadata`, `temperature`, `top_p`, `prompt`, `tool_search`, hosted MCP, file search, code interpreter, and more.
- **Errors** (https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery): `subscription_sharing_usage_limit_exceeded` (429: stop sending and point the user at ChatGPT Settings → Usage), `subscription_sharing_usage_unavailable` / `…_user_unavailable` (503, bounded backoff), `subscription_sharing_user_not_eligible` (403, do not loop), refresh errors (`refresh_token_reused`, `refresh_token_expired`, …: clear tokens and re-run OAuth).
- **Quota visibility**: users set per-app weekly caps (Settings → Usage → App limits; https://learn.chatgpt.com/docs/sign-in-with-chatgpt); there is no API for remaining quota on SIWC tokens; an OpenAI maintainer said it is not supported for now (openai/sign-in-with-chatgpt-devkit#3).
- **Headless**: no device-code flow is documented for SIWC. The "Self-hosted VMs" recipe: create the VM's own `ext_agent_host_id`, complete OAuth on a machine with a browser for the same user and client, move `client_id/access_token/refresh_token/id_token` over SSH, keep the VM's host ID, and let the VM own later refreshes (https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).
- **Libraries**: official DevKit `openai/sign-in-with-chatgpt-devkit` (Node.js `@siwc/local` + React; TypeScript; created 2026-09-29, 48 stars, *SIWC DevKit Noncommercial License v1.0*). **No Python library** — for a Python graph we write the OAuth (about 150 lines with `httpx`) or run the DevKit as a token sidecar. Open-source implementations to read: OpenCode (anomalyco/opencode, 213k stars, MIT) and CLIProxyAPI both contain `dynamic_agent_client` code; OpenClaw, Pi, T3 are the listed open-source integrations.
- **LangChain wiring** (inferred, needs a spike): `ChatOpenAI(model=<slug>, use_responses_api=True, base_url="https://api.openai.com/v1", api_key=<callable returning a fresh token>, streaming=True, store=False)`; `langchain-openai` 1.7.1 (2026-10-12) accepts `api_key` as `SecretStr | Callable[[], str] | Callable[[], Awaitable[str]]` and defaults `temperature=None` (`libs/partners/openai/langchain_openai/chat_models/base.py` L804-811, L1224, L1274). `openai-python` refreshes callable keys per request (`src/openai/_client.py` L167, L703-705). Risk: LangChain may send a field the preview rejects; test `bind_tools` and `with_structured_output` first.
- **Codex on SIWC tokens**: OpenAI documents running `codex app-server` on a SIWC token through a custom provider: `model_provider="openai_chatgpt_plan"`, `model_providers.openai_chatgpt_plan = { base_url="https://api.openai.com/v1", env_key="ACCESS_TOKEN", wire_api="responses", requires_openai_auth=false, supports_websockets=false }`, and restart app-server with a new `ACCESS_TOKEN` after refresh (https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server). Preview note: app-server must not emit `tool_search`. Inferred improvement: Codex providers also accept a command-backed token, `model_providers.<id>.auth = { command, args, timeout_ms (default 5000), refresh_interval_ms (default 300000; 0 = only after 401) }` (`codex-rs/protocol/src/config_types.rs` L564-601), which would avoid hourly restarts. Not in the SIWC doc; spike before relying on it.

#### B2. Unofficial route: reuse the Codex CLI's OAuth client against the ChatGPT backend (verified mechanics, undocumented endpoint)
All of these log in with the Codex CLI's public client ID `app_EMoamEEZ73f0CkXaXp7hrann` and call `https://chatgpt.com/backend-api/codex/responses` with `Authorization: Bearer`, `ChatGPT-Account-Id`, `originator`, `session_id`, and usually a Codex-like `User-Agent`. In other words, they present themselves as the Codex CLI.

| Project | Lang / form | Stars, license, activity (2026-10-13) | Mechanics | Notes |
|---|---|---|---|---|
| **LiteLLM `chatgpt/` provider** (BerriAI/litellm) | Python SDK + proxy | 61k stars; license NOASSERTION (MIT core plus an enterprise dir); pushed 2026-10-13; provider added 2026-01-19 (#19030), last touched 2026-10-07; litellm 1.105.0 (2026-10-11) | Device-code login on first use; tokens in `~/.config/litellm/chatgpt/auth.json` (`CHATGPT_TOKEN_DIR`, `CHATGPT_AUTH_FILE`); default `originator=codex_cli_rs` and a `codex_cli_rs/…` User-Agent; strips `max_tokens`, `max_output_tokens`, `metadata`; one account per process; refresh tokens single-use; file rewritten in place, not atomically. Sources: `litellm/llms/chatgpt/common_utils.py` L15-24, L228-247; https://docs.litellm.ai/docs/providers/chatgpt | Most mature Python option. Reaches LangChain via `langchain-litellm` 0.11.0 `ChatLiteLLM(model="chatgpt/…")` or LiteLLM proxy + `ChatOpenAI(base_url=…)`. |
| **ChatMock** (RayBytes/ChatMock) | Python local server | 1.6k stars, MIT; last code change 2026-07-26 (1.40 on PyPI) | `chatmock login [--headless]`, `chatmock serve` → `http://127.0.0.1:8000/v1` (chat completions + `/v1/responses`, Ollama API); discovers the account's models. | Point `ChatOpenAI(base_url=…)` at it. Slowing maintenance. |
| **openai-oauth** (EvanZhouDev/openai-oauth) | Node proxy + TS SDK | 1.4k stars, Apache-2.0; v2.0.0 2026-07-15; last commit 2026-09-29 | `npx openai-oauth` → `http://127.0.0.1:10531/v1`; reuses the local Codex login (`npx openai-oauth login` if absent). Its README says it is unofficial and tells users not to pool or share tokens or bypass limits. | Node sidecar; fine as a reference. |
| **CLIProxyAPI** (router-for-me/CLIProxyAPI) | Go proxy | 55k stars, MIT; v8.0.27 2026-10-12 | Codex OAuth with **multi-account round-robin**; sponsored by token-resale "relay" services. Also has SIWC `dynamic_agent_client` code. | **Avoid**: built around pooling, which the ToS forbids, and a ban report exists (router-for-me/CLIProxyAPI#3431, cause unconfirmed). |
| **langchain-codex-oauth** (AnthonyTlei) | Python, native LangChain `ChatCodexOAuth` | 14 stars, MIT; marked "[LEGACY]" 2026-08-03; PyPI 1.0.0 2026-01-15 | Own OAuth login, SSE streaming, `bind_tools`. | Abandoned; shows how small an adapter is. |

Risks of B2: the endpoint is undocumented and may change or add checks at any time; impersonating the first-party client conflicts with the ToS rule against programmatic extraction except through the API (§3); and because SIWC now exists, there is less reason for OpenAI to tolerate B2 indefinitely (inferred). The model sees no Codex harness, so we would build our own tool loop (file edits, shell, sandbox) in LangGraph, which is a lot of work for a prototype.

### 2.3 Option C — route through a gateway that already holds the login (brief)
- OpenClaw gateway exposes OpenAI-compatible `POST /v1/chat/completions`, `GET /v1/models`, `POST /v1/embeddings`, plus `POST /v1/responses` behind `gateway.http.endpoints.responses.enabled`. Chat completions are disabled by default (`gateway.http.endpoints.chatCompletions.enabled`); bearer auth with the gateway token or password. The `model` field selects an **OpenClaw agent** (`openclaw`, `openclaw/<agentId>`), not a raw model, and each request runs as a full agent run; `x-openclaw-model` overrides the backend model and needs `operator.admin`. The docs say to treat it as full operator access (https://docs.openclaw.ai/gateway/openai-http-api).
- OpenClaw's OpenAI provider uses Codex OAuth for subscriptions and ships a bundled Codex app-server runtime (`agentRuntime.id: "codex"`); its docs claim OpenAI supports subscription OAuth in tools like OpenClaw (https://docs.openclaw.ai/providers/openai). OpenAI lists OpenClaw as an open-source SIWC integration and a DevDay launch partner.
- Fit: wrong for this prototype (it runs outside OpenClaw; the endpoint is agent-shaped and admin-equivalent). Later, when OpenClaw supervises the workflow, OpenClaw can be the thing that holds the ChatGPT login and hands the graph a scoped credential.

## 3. Policy and risk

### 3.1 What OpenAI's documents say (fetched 2026-10-13)
| Source | What it says (paraphrased) | Status |
|---|---|---|
| Terms of Use (https://openai.com/policies/terms-of-use/; direct fetch blocked with 403, read through search excerpts) | No automated or programmatic extraction of data or output **except as permitted through the API**; do not share account credentials or make the account available to anyone else; do not circumvent rate limits or restrictions. | verified (excerpt) |
| Sign in with ChatGPT Terms (https://openai.com/policies/sign-in-with-chatgpt-terms/, updated about 2026-09-30; fetch blocked, read through search excerpts) | Plan-usage requests must come from the user's local runtime, or a remote runtime only that user controls; they must be for the authenticated user and arise from the user's activity **or expressly authorised automations or background processes**, with express consent before background use; another user's activity must not trigger requests on the account; no pooling or sharing; no extra accounts to dodge limits; use the plan only for the app the user connected. | verified (excerpt) |
| Codex CI/CD auth guide (https://learn.chatgpt.com/docs/auth/ci-cd-auth) | ChatGPT-managed Codex auth is a documented, advanced pattern for "enterprise and other trusted private automation"; API keys remain the recommendation for most CI; do not use it on public or open-source repositories; one `auth.json` per runner or serialised stream. | verified |
| Non-interactive mode (https://learn.chatgpt.com/docs/non-interactive-mode) | API key recommended for CI; ChatGPT auth only on trusted runners; never on public repos; never put `OPENAI_API_KEY`/`CODEX_API_KEY` in job-level env where untrusted code runs. | verified |
| Pricing (https://learn.chatgpt.com/docs/pricing) | Local and cloud Codex use share one plan allowance; API keys suit automation in shared environments such as CI. | verified |
| SIWC developer docs (https://developers.openai.com/siwc/token-sharing-open-source) | Plan usage offered to open-source and locally hosted apps; paid or remote apps use an interest form. | verified |
| Codex for Open Source (https://developers.openai.com/community/codex-for-oss) | OpenAI says developers should code in the tools they prefer, naming OpenCode, Cline, pi and OpenClaw. A statement of posture, not a licence grant. | verified |

### 3.2 Reading for our prototype (inferred)
- **Running the official Codex client (CLI, Python SDK, app-server) unattended on a private repo, with a login Alex created for that purpose, matches what OpenAI documents.** It is Alex's own expressly authorised automation, on his own machine, on private repos.
- **SIWC tokens from our own Python code are the sanctioned way to call the model directly** (they go to the public API endpoint). The SIWC Terms explicitly cover authorised background automation.
- **Reusing the Codex CLI client ID from a non-Codex program to call `chatgpt.com/backend-api/codex`** (LiteLLM `chatgpt/`, ChatMock, openai-oauth, langchain-codex-oauth) is not covered by any OpenAI document. It presents as the Codex CLI and sits close to the ToS clause on programmatic extraction outside the API. Many projects do it and OpenClaw's own docs claim OpenAI supports subscription OAuth in tools like OpenClaw. Now that SIWC exists, I would not build new work on it.
- **Trigger hygiene matters**: since the SIWC Terms say another user's activity must not trigger requests, S1 should only start work on issues that Alex authored or explicitly approved (for example, a label only he can apply), not on any issue a third party opens. That is also good prompt-injection hygiene.
- **Never** pool accounts, rotate between several accounts to dodge limits, or put Alex's personal login on a shared or public CI runner.

### 3.3 Enforcement and stability evidence
- Account bans with generic terms-violation notices and no stated cause appear on the OpenAI forum (for example https://community.openai.com/t/codex-chatgpt-pro-account-banned-with-no-warning-no-explanation-18-month-subscriber/1381906, 2026-05-27; that user used no third-party tools and suspected a datacenter IP). A CLIProxyAPI user reports a ban of unconfirmed cause (router-for-me/CLIProxyAPI#3431, 2026-05-16). I found **no confirmed OpenAI enforcement against single-user use of the official Codex client in automation.** Detection is opaque, so the realistic risk is a false positive from odd traffic (datacenter egress, many parallel sessions), not a published rule. (verified reports; cause unverified)
- Undocumented backend: `chatgpt.com/backend-api/codex` is what Codex itself calls (`codex-rs/model-provider-info/src/lib.rs` L80, L426-445), so it changes whenever Codex does (several releases a week). Third-party clients break: open LiteLLM bugs include empty `output[]` on completed responses (BerriAI/litellm#41009, #25429, #26179), streaming-mode rejections (#28044) and dropped parallel tool-call arguments (#45348). LiteLLM users already ask for SIWC support (#43925, 2026-09-30). The SIWC API surface is documented but in preview, with unsupported parameters listed (§2.2 B1).
- Codex's own interfaces churn: `codex mcp-server` went from deprecation warning to removal in 16 days (2026-08-20 → 2026-09-05); `--full-auto` is deprecated. Pin the CLI or SDK version and upgrade deliberately.

### 3.4 Risk register for the subscription path
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Refresh-token race → `refresh_token_reused` → login dead mid-run | Medium if two processes share a `CODEX_HOME`; low with one long-lived app-server | Workflow blocks until a human logs in again | One app-server per `CODEX_HOME`; never copy `auth.json`; route the `refresh_token_*` errors to S10 (`blocked: re-login needed`). |
| Workflow drains Alex's interactive quota (shared 5 h and weekly windows) | High on Plus | Alex's own Codex stops working | Read `account/rateLimits/read` before each S3/S7 run and stop above a threshold (for example 70% of either window); under SIWC also set the per-app weekly cap. |
| Token theft by a prompt-injected agent shell | Medium (it reads issue text, CI logs, repo files) | Account takeover until revoked | §4 isolation; dedicated login revocable through `codex logout` (revokes) or ChatGPT security settings; egress allowlist. |
| Upstream change breaks the harness | Medium (weekly releases) | Prototype stops | Pin `openai-codex==X` (it pins the CLI binary); smoke-test before bumping. |
| Plan or policy change (limits, eligibility) | Medium | Cost or availability | API-key fallback with zero code change (Codex harness). |

## 4. Container patterns ("canned workflow container")

### 4.1 What OpenAI ships (verified)
| Artifact | What it is | Status | Use for us |
|---|---|---|---|
| `ghcr.io/openai/codex-universal` (openai/codex-universal) | Reference copy of the Codex **cloud** base image: language toolchains selected with `CODEX_ENV_*` variables. Does not cover auth. amd64 is the only arch OpenAI runs; arm64 is built with small differences. | 1,096 stars, **no licence file**, last push 2026-05-02 (5 months stale) | Optional base for toolchains; too heavy for a prototype on Apple Silicon. |
| `codex-cli/scripts/run_in_container.sh` + `init_firewall.sh` (openai/codex) | Legacy script: runs Codex in a container with an iptables **egress allowlist** (`OPENAI_ALLOWED_DOMAINS`, needs `NET_ADMIN`), passes `OPENAI_API_KEY`, starts `codex --sandbox workspace-write`. The image it names has no Dockerfile in the repo any more. | Present at rust-v0.162.1; API-key era | Copy the egress-allowlist idea. ChatGPT auth needs `auth.openai.com` and `chatgpt.com` on the allowlist. |
| `openai/codex-action` | GitHub Action: runs `codex exec` with `safety-strategy` = `drop-sudo` (default), `unprivileged-user`, `read-only` or `unsafe`, and a `codex-home` input. Its docs warn that without privilege separation the agent can read the API key from memory. | 1,266 stars, Apache-2.0, pushed 2026-10-09 | Reference for the **credential holder ≠ agent user** pattern. |
| `codex responses-api-proxy` | Holds an API key (read from stdin, `mlock`ed, process-hardened) and forwards only `POST /v1/responses`; meant to run as a privileged user while Codex runs unprivileged. | In-tree, internal subcommand | **API key only** (static bearer, no OAuth refresh). Right tool for the API-key fallback. |

Community images are thin and lightly maintained: icoretech/codex-docker (9 stars, multi-arch, follows upstream releases, no licence), dirien/devcontainer-feature-codex (7 stars, MIT, pushed 2026-10-05), ungb/codex-docker (5 stars, MIT, stale since 2025-12-31). **Build our own small image** (python, node, git, our toolchain, plus `pip install openai-codex==<pin>`, which brings the pinned CLI binary).

### 4.2 Log in once, persist, refresh safely (verified mechanics; layout inferred)
1. Create a **dedicated workflow login**. Do not copy Alex's interactive `~/.codex/auth.json` (§1.4). Either:
   - Container: `docker run --rm -it -e CODEX_HOME=/codex-home -v oc2-codex-home:/codex-home <image> codex login --device-auth`. Device-code login must first be enabled in ChatGPT security settings; the code expires in 15 minutes.
   - Mac: `mkdir -m 700 ~/.codex-workflow && CODEX_HOME=~/.codex-workflow codex login` (or `--device-auth`).
2. Keep `cli_auth_credentials_store = "file"` (the default; containers have no keyring). Codex writes `auth.json` with mode 0600 and refreshes it in place (access token within 5 minutes of expiry, or `last_refresh` older than 8 days), so the volume must be writable and persistent.
3. **Exactly one long-lived Codex process per `CODEX_HOME`**: one app-server that serves every concurrent task as separate threads. Avoid parallel `codex exec` processes on the same home, since there is no cross-process lock (§1.3).
4. Never restore an old `auth.json` from a backup or image layer; a stale refresh token fails as `refresh_token_reused`. Recovery is to log in again, so S10 should say so plainly.
5. Monitor: `codex login status`, or `codex.account()` / `account/read` from the SDK at graph start; route `refresh_token_*` failures to S10.

### 4.3 Keeping the token away from the agent's own shell
Codex runs tool commands as the **same OS user** as the app-server, and by default its sandbox restricts writes and network, **not reads**. So `cat $CODEX_HOME/auth.json` works unless we prevent it. Options, from strongest to weakest:

| # | Pattern | Evidence | Maturity | Notes |
|---|---|---|---|---|
| a | **Split the harness from execution.** The app-server (holding `CODEX_HOME`) runs on the host or in a trusted container; every shell and file operation runs in the task container through `codex exec-server`. In `$CODEX_HOME/environments.toml`: `include_local = false`, `default = "sandbox"`, `[[environments]] id = "sandbox"`, `program = "docker"`, `args = ["exec","-i","sbx-<task>","codex","exec-server","--listen","stdio"]` (or `url = "ws://…"` + `auth_bearer_token`). The task container holds the worktree only: no ChatGPT or GitHub credentials. | Fields: `codex-rs/exec-server/src/environment_toml.rs` L26-55; `--listen stdio`, `--ws-auth capability-token`: exec-server help snapshot; `environment/add` in the app-server protocol | **Experimental** (so labelled in the CLI help); open issues on executor selection (openai/codex#50374) | Best isolation and fits the "canned container" idea. Needs a spike: confirm `apply_patch` and file reads also go through the remote environment. |
| b | **Deny-read permission profile.** `default_permissions = "builder"`; `[permissions.builder.filesystem] ":minimal" = "read"` and `"<CODEX_HOME path>" = "deny"`; `[permissions.builder.filesystem.":workspace_roots"] "." = "write"` (https://learn.chatgpt.com/docs/permissions). | Enforced by Seatbelt on macOS. On Linux it needs bubblewrap with unprivileged user namespaces, which usually fail in Docker (openai/codex#16211), and the Landlock fallback does not enforce read restrictions (openai/codex#11316, still open). | macOS: usable now (inferred; verify with a canary). Linux containers: fragile. | **Phase 1 on the Mac**: run the app-server natively under Seatbelt with this profile, no Docker. |
| c | **SIWC broker.** The host owns the SIWC refresh token; Codex gets only a 1-hour, plan-usage-scoped access token through the documented custom provider (`env_key="ACCESS_TOKEN"`, restart on refresh), or through `model_providers.<id>.auth.command` (inferred). | §2.2 B1 | Preview (2 weeks old) | The refresh token never enters the agent's world; worst-case leak is one hour of plan usage. |
| d | **Separate UID / privileged credential holder** (codex-action pattern) | `openai/codex-action/action.yml` `safety-strategy` | Official for API keys | For ChatGPT OAuth, no official equivalent of `responses-api-proxy` exists. |
| e | **Defence in depth (always).** Codex drops `*KEY*`, `*SECRET*`, `*TOKEN*` env vars from tool commands by default (`codex-rs/protocol/src/shell_environment.rs` L125-130), but `include_only` was reported leaking app-server env vars into `exec_command` (openai/codex#48096, open). The Python SDK copies the **whole parent environment** into the app-server (`sdk/python/src/openai_codex/client.py` L258-261). Keep `workspace-write` network off (`network_access` defaults to false, `codex-rs/config/src/types.rs` L1134-1143); add an egress allowlist; use a dedicated, revocable login (`codex logout` revokes tokens at `auth.openai.com/oauth/revoke`). | as cited | n/a | **Never start the SDK from a process whose env holds `GH_TOKEN` or similar.** Load the GitHub credential only inside the S5/S9 node, or pass a scrubbed env through `launch_args_override=("env","-i",…,"codex","app-server","--listen","stdio://")` (inferred). Add a canary test: ask the agent to read the auth file and assert it fails. |

### 4.4 Suggested layout for the prototype (inferred)
- **Phase 1 (Mac, no Docker for the agent):** LangGraph process on macOS with a SQLite checkpointer. `AsyncCodex(CodexConfig(env={"CODEX_HOME": "~/.codex-workflow"}, cwd=<task worktree>))`. Seatbelt sandbox with the deny-read profile (4.3 b). Network off for agent commands; deterministic nodes do installs. GitHub credential exists only in S2/S5/S6/S9 code paths.
- **Phase 2 (container):** a per-task `sbx-<task>` container (worktree mounted, no secrets, egress allowlist) running `codex exec-server --listen stdio`, driven by one host app-server through `environments.toml` (4.3 a). Optionally swap Codex-managed auth for a SIWC broker (4.3 c) once spiked.
- **Restart and resume:** store the Codex `thread_id` in LangGraph state. After a crash, `thread_resume(thread_id)`, then check `git status`/diff before re-issuing the turn, because a turn is not idempotent. Before each S3/S7 turn, read `account/rateLimits/read`. If over budget or `rate_limit_reached_type` is set, `interrupt()` (S10) with `resets_at` as the earliest resume time.

## 5. Fit per workflow step (S1–S10, X)

Assumes the primary recommendation: the Codex harness through `openai-codex` on a dedicated Codex ChatGPT login.

| Step | Uses the subscription? | How (verified API; wiring inferred) |
|---|---|---|
| S1 Intake | No (deterministic) | GitHub API plus a rule check for an acceptance-criteria section. Only accept issues Alex authored or labelled (SIWC Terms trigger rule, §3.2; prompt-injection hygiene). If an LLM check is ever wanted: one read-only Codex turn with `output_schema`. |
| S2 Workspace | No | Worktree or clone, plus the task container in Phase 2. Fresh Codex `thread_start(cwd=worktree)`. |
| S3 Build | **Yes** | One builder thread per task: `thread_start(sandbox=Sandbox.workspace_write, approval_mode=ApprovalMode.deny_all, developer_instructions=…)`, then `thread.run(task, output_schema=DONE_SCHEMA)`. Feed the issue body, CI logs and review findings as `ExternalMessage` (tool-level authority). Note: the SDK **defaults to `ApprovalMode.auto_review`**, where a reviewer Codex agent approves sandbox escalations (`sdk/python/src/openai_codex/_approval_mode.py`; https://learn.chatgpt.com/docs/sandboxing/auto-review). Use `deny_all` (approval policy `never`) so no LLM grants escalations. |
| S4 Local gate | No | Deterministic. On failure, `thread_resume(builder_thread_id)` and `run(ExternalMessage(test_log))`, bounded by a counter in graph state. |
| S5 Publish | No | Deterministic and holds the GitHub credential. Never put it in the app-server's environment (§4.3 e). |
| S6 CI wait | No | Deterministic polling of check runs; red → failing job log → S3 as an `ExternalMessage`. |
| S7 Review | **Yes** | Separate reviewer thread with fresh context and a read-only sandbox (use `workspace_write` on a throwaway copy if the reviewer must run tests that write caches). Either Codex's built-in review (`review/start`, or `codex exec review --base <branch>`), which returns `ReviewOutputEvent` findings with priority and confidence, or `thread.run(prompt, output_schema=VERDICT_SCHEMA)`. |
| S8 Review-fix loop | Yes (via S3/S7) | Same builder thread resumed with findings; bounded rounds in graph state. |
| S9 Merge-ready | No | Deterministic: mark ready, post summary, stop. |
| S10 Blocked | No | LangGraph `interrupt()`. Route here: `refresh_token_*` auth errors (re-login), quota (`rate_limit_reached_type` / used% over threshold, resume after `resets_at`), `subscription_sharing_*` errors if on SIWC. |
| X Checkpoint/resume | — | LangGraph checkpointer (SQLite) holds the Codex `thread_id`s; Codex rollouts persist under `$CODEX_HOME/sessions` (`codex-rs/rollout/src/lib.rs` L86; do not use `ephemeral` for builder threads). |
| X Budgets | — | Per-turn `TurnResult.usage` (or `turn.completed.usage` in exec JSONL) for token budgets; `account/rateLimits/read` for plan windows (reach it through `CodexClient.request(...)` — the high-level SDK only wraps `account()`; inferred). |
| X Stuck detection | — | Wrap `turn.stream()` with a wall-clock timeout and call `TurnHandle.interrupt()`. |
| X Observability | — | Codex defaults: OTel log and trace exporters `None`, **metrics exporter `Statsig`** (`codex-rs/config/src/types.rs` L667-680). Analytics and feedback can be turned off (`[analytics] enabled=false`, `[feedback] enabled=false`, L241-256). For no vendor telemetry by default set `[otel] metrics_exporter = "none"` (or a local OTLP endpoint) and `[analytics] enabled = false` in the workflow `CODEX_HOME/config.toml`. Prompts and code still go to OpenAI as the model provider. |
| X Secret isolation / sandbox | — | §4.3. |

## 6. Sources

### 6.1 Repositories (checked 2026-10-13 with `gh api`)
| Repo | Stars | Licence | Last push | Maintained? | Role here |
|---|---|---|---|---|---|
| openai/codex | 128,969 | Apache-2.0 | 2026-10-13 (rust-v0.162.1 stable 2026-10-09) | Yes, very active | CLI, app-server, Python/TS SDKs, auth source |
| openai/codex-action | 1,266 | Apache-2.0 | 2026-10-09 | Yes | Privilege-separation pattern (API key) |
| openai/codex-universal | 1,096 | none | 2026-05-02 | Slow | Cloud base image reference |
| openai/sign-in-with-chatgpt-devkit | 48 | SIWC DevKit Noncommercial v1.0 | 2026-10-07 (created 2026-09-29) | Yes, new | Official SIWC Node SDK + example |
| openai/openai-python | 31,835 | Apache-2.0 | 2026-10-13 | Yes | Callable `api_key` for SIWC tokens |
| langchain-ai/langchain (`langchain-openai` 1.7.1, 2026-10-12) | 147,746 | MIT | 2026-10-13 | Yes | `ChatOpenAI` Responses API, callable key |
| langchain-ai/langgraph | 43,189 | MIT | 2026-10-13 | Yes | Orchestrator |
| langchain-ai/langchain-mcp-adapters | 3,652 | MIT | 2026-09-16 | **Archived** (moved to `langchain[mcp]`) | Moot: `codex mcp-server` removed |
| BerriAI/litellm (1.105.0, 2026-10-11) | 61,132 | NOASSERTION (MIT core + enterprise dir) | 2026-10-13 | Yes | `chatgpt/` provider (Codex client ID route) |
| RayBytes/ChatMock (PyPI 1.40, 2026-07-26) | 1,557 | MIT | 2026-09-01 | Slowing | Local OpenAI-compatible proxy (Codex client ID route) |
| EvanZhouDev/openai-oauth (npm 2.0.0, 2026-07-15) | 1,401 | Apache-2.0 | 2026-09-29 | Yes | Node proxy/SDK (Codex client ID route) |
| router-for-me/CLIProxyAPI (v8.0.27, 2026-10-12) | 55,037 | MIT | 2026-10-13 | Yes | Multi-account pooling proxy: avoid |
| AnthonyTlei/langchain-codex-oauth (PyPI 1.0.0, 2026-01-15) | 14 | MIT | 2026-08-13 | **Legacy** | Native LangChain adapter, abandoned |
| numman-ali/opencode-openai-codex-auth | 2,212 | NOASSERTION | 2026-01-09 | Superseded by OpenCode's built-in login | Historical |
| anomalyco/opencode (ex sst/opencode) | 213,084 | MIT | 2026-10-13 | Yes | Built-in ChatGPT Plus/Pro login; has SIWC `dynamic_agent_client` code |
| earendil-works/pi (ex badlogic/pi-mono) | 114,791 | MIT | 2026-10-13 | Yes | SIWC open-source integration (TypeScript) |
| openclaw/openclaw | 391,835 | MIT | 2026-10-13 | Yes | Gateway; SIWC launch partner; bundled Codex app-server runtime |
| icoretech/codex-docker | 9 | none | 2026-10-10 | Yes, tiny | Community multi-arch Codex image |
| dirien/devcontainer-feature-codex | 7 | MIT | 2026-10-05 | Yes, tiny | Devcontainer feature |
| ungb/codex-docker | 5 | MIT | 2025-12-31 | Stale | Community image |

### 6.2 Key permalinks (openai/codex @ rust-v0.162.1)
- Auth manager (refresh intervals, error codes, client ID, precedence): https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/login/src/auth/manager.rs (L203-216, L953-970, L1489-1590, L1600-1718, L2840-2878, L3001-3023)
- Auth storage (auth.json shape, 0600, keyring key): https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/login/src/auth/storage.rs (L47-73, L160-258)
- Browser login server: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/login/src/server.rs (L77-78, L586-617, L1023-1045)
- Device code: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/login/src/device_code_auth.rs (L60-200)
- Access tokens (`at-` prefix, whoami): https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/login/src/auth/access_token.rs and `personal_access_token.rs` (L11-13)
- `cli_auth_credentials_store` default, `SandboxWorkspaceWrite`, analytics/OTel defaults: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/config/src/types.rs (L133-146, L241-256, L667-680, L1134-1143)
- `CODEX_HOME` resolution: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/utils/home-dir/src/lib.rs (L13-50)
- ChatGPT backend base URL: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/model-provider-info/src/lib.rs (L80, L426-445)
- Command-backed provider token: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/protocol/src/config_types.rs (L564-601)
- Default env excludes: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/protocol/src/shell_environment.rs (L125-130)
- App-server account protocol (`chatgptAuthTokens` internal-only, rate limits): https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server-protocol/src/protocol/v2/account.rs (L86-99, L271-345, L650-760)
- Review output schema: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/protocol/src/protocol.rs (L3505-3545)
- exec CLI and JSONL events: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/exec/src/cli.rs, https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/exec/src/exec_events.rs
- exec-server and environments.toml: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/exec-server/README.md, https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/exec-server/src/environment_toml.rs
- responses-api-proxy: https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/responses-api-proxy/README.md
- Python SDK: https://github.com/openai/codex/tree/rust-v0.162.1/sdk/python (README, docs/getting-started.md, docs/faq.md, docs/api-reference.md, src/openai_codex/client.py L195-275, src/openai_codex/_approval_mode.py)
- mcp-server removal: https://github.com/openai/codex/commit/531f3836a1 (#42993), deprecation https://github.com/openai/codex/commit/5e3a6fe4ee (#39657)
- Issues: #10332 (refresh race, maintainer on reuse window), #11316 (Landlock read restrictions not enforced), #16211 (bwrap in Docker), #48096 (env leak despite include_only), #50374 (remote executor selection)

### 6.3 Official docs (fetched 2026-10-13; `developers.openai.com/codex/*` now 308-redirects to `learn.chatgpt.com/docs/*`)
- Auth: https://learn.chatgpt.com/docs/auth · CI/CD auth (advanced): https://learn.chatgpt.com/docs/auth/ci-cd-auth · Access tokens: https://learn.chatgpt.com/docs/enterprise/access-tokens
- Non-interactive: https://learn.chatgpt.com/docs/non-interactive-mode · SDK: https://learn.chatgpt.com/docs/codex-sdk · App-server: https://learn.chatgpt.com/docs/app-server
- Pricing and limits: https://learn.chatgpt.com/docs/pricing · Permissions: https://learn.chatgpt.com/docs/permissions · Sandboxing: https://learn.chatgpt.com/docs/sandboxing · Auto-review: https://learn.chatgpt.com/docs/sandboxing/auto-review
- SIWC: https://learn.chatgpt.com/docs/sign-in-with-chatgpt · https://developers.openai.com/siwc · /siwc/quickstart · /siwc/token-sharing-open-source (+ /sign-in, /profiles-and-sessions, /models-and-inference, /codex-app-server, /self-hosted-vms, /token-reference, /errors-and-recovery, /preview-limitations) · cookbook https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt
- Terms (fetch returned 403; read through search excerpts): https://openai.com/policies/terms-of-use/ · https://openai.com/policies/sign-in-with-chatgpt-terms/
- Codex for Open Source: https://developers.openai.com/community/codex-for-oss
- Third-party docs: LiteLLM https://docs.litellm.ai/docs/providers/chatgpt · OpenClaw https://docs.openclaw.ai/gateway/openai-http-api, https://docs.openclaw.ai/providers/openai · OpenCode https://opencode.ai/docs/providers/
- News: TechCrunch 2026-09-29 (SIWC at DevDay) https://techcrunch.com/2026/09/29/openais-latest-features-take-direct-aim-at-the-app-store-model/
