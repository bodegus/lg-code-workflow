# Pinned Codex thread policy config shapes

Question: which public thread-start config shape preserves workspace networking, and does
read-only remain isolated with explicit never approval? Expected at least one of dotted/nested
workspace config shapes to work, with read-only networking disabled. No model turn is started.

## Calls and evidence

Pinned SDK/runtime: 0.162.1. The live-guarded ignored probe creates a temporary HOME/CODEX_HOME
and empty checkout, starts AsyncCodexClient with the verified env-clearing launch hook, calls
initialize, and calls thread_start three times using public generated ThreadStartParams:

- sandbox=workspace_write, config={"sandbox_workspace_write.network_access": true}
- sandbox=workspace_write, config={"sandbox_workspace_write": {"network_access": true}}
- sandbox=read_only, config={"sandbox_workspace_write.network_access": true}

Each request sets AskForApproval(root=AskForApprovalValue.never). The probe examines the server's
returned sandbox policy and approval policy, then closes the client. It uses no private SDK
attributes or imports. An initial source-inspection import looked for ThreadStartResponse in
models.py; the public generated/v2_all.py is its actual location. That inspection made no calls.

```text
$ uv run python - [run_process driver, argv: uv run python spikes/2026-10-13-codex-policy/probe.py; env LGCW_LIVE=1; timeout_s=45]
exit 0
{"approval": "never", "network": true, "shape": "dotted", "type": "workspaceWrite"}
{"approval": "never", "network": true, "shape": "nested", "type": "workspaceWrite"}
{"approval": "never", "network": false, "shape": "read_only", "type": "readOnly"}
thread policy probe complete; model turns: 0; authentication API calls: 0
```

Verdict: both shapes confirmed by returned effective policy. Read-only ignores the workspace-only
network setting and retains network=false. This is policy/API evidence, not an OS write or network
access test. Those require the later T10 paid-turn spike. Also, the high-level turn sandbox preset
constructs a fresh policy with network=false by default (_sandbox.py); the harness must not reset
an explicitly enabled builder network policy accidentally when starting a turn. T10 must verify
resumed policy and real write denial, along with structured output, usage and cancellation.

Transcript: /tmp/lgcw-codex-policy-probe.log. No owner login was read or copied; all created thread
state was in the removed temporary CODEX_HOME. This probe does not qualify the full harness.
