# Actions read boundary — 2026-10-13

**Question:** Does the pinned githubkit adapter return real typed jobs and plain-text job logs
through the redirected download endpoint, including failed-job annotations?

**Expected:** yes; all three family-calendar CI jobs and the audit log are readable.

**Authority/scope:** D-032's owner-authorized family-calendar sandbox contract fixture, closed
PR #25, rather than a new target run. Read-only; no PR/issue/branch/comment/rerun write and no
agent turn. This supplements T15's adapter qualification and the final current-head CI guard.
The script is throwaway under gitignored spikes/2026-10-13-actions-read/.

**Command:**

```sh
LGCW_LIVE=1 uv run python spikes/2026-10-13-actions-read/probe.py
```

**Actual output:**

```json
{
  "repo": "bodegus/family-calendar",
  "pr": 25,
  "pr_state": "CLOSED",
  "head": "617b1ea5857163dac0d239b26d91fdb97424def3",
  "runs": [
    [
      38441965084,
      1,
      "CI"
    ]
  ],
  "jobs": [
    [
      115450536032,
      "Node 26.8.1",
      "success",
      [],
      0
    ],
    [
      115450536348,
      "Node 24.20.0",
      "failure",
      [
        "Audit production dependencies"
      ],
      2
    ],
    [
      115450760985,
      "Container build and smoke test",
      "skipped",
      [],
      0
    ]
  ],
  "log_characters": 39932,
  "trimmed_bytes": 8192,
  "contains_proxy_addr": true,
  "contains_npm_audit": true,
  "is_html": false,
  "model_turns": 0,
  "github_writes": 0
}
```

**Verdict:** confirmed. jobs_for_run includes the real failing step and two check annotations;
job_log follows the download redirect and yields plain text, not an HTML redirect response.
trim_job_log respects its 8 KiB bound on this actual log. No adapter change follows. A failed or
skipped required job remains non-green; this read probe is not a merge-ready workflow run.
Only metadata and byte counts are retained here, not the full real job log.
