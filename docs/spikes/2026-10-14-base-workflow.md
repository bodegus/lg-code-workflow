# Workflow-specific base lookup: GitHub expects the filename

Question: does pinned githubkit0.16.1 Actions async_list_workflow_runs accept the complete
RunView.workflow_path or require the filename? Expected: filename may be required.
Read-only own repository, D-008 SDK, no new dependency or HTTP client.

```text
LGCW_LIVE=1 uv run python spikes/2026-10-14-base-workflow/probe.py
{
  "observations": [
    {"workflow_id": ".github/workflows/ci.yml", "status": 404},
    {"workflow_id": "ci.yml", "status": 200, "runs": [38473073579]}
  ],
  "model_turns": 0,
  "github_writes": 0
}
```

Verdict: full path refuted; filename confirmed on the actual endpoint. The synthetic endpoint
regression was strengthened to require /actions/workflows/pr-only.yml/runs and failed first
with the full path. Normalize the filename before the public SDK request. The ordinary base
branch/event/status filters and per_page=1 still apply; unrelated push histories are never read.
The repaired adapter itself then passed:

```text
LGCW_LIVE=1 uv run python spikes/2026-10-14-base-workflow/adapter_probe.py
{
  "workflow_path": ".github/workflows/ci.yml",
  "jobs": [[38473073579, "check", "success"]],
  "model_turns": 0,
  "github_writes": 0
}
```

Probe source is throwaway under spikes/, no credentials or log bodies are committed. This is
adapter qualification, not a full Phase1 workflow run.
