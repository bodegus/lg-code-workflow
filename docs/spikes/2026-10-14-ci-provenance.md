# Existing Actions annotation provenance — read-only, partial qualification

Question: can existing failed Actions runs supply real runner-loss and literal printed
`::error` annotations, their path and check output, without manufacturing a failure?
Expected: an ordinary user-command failure may be available; runner loss may not be.
Pinned githubkit0.16.1, same D-032 authorized closed T5 fixture. Probe source is throwaway under
`spikes/2026-10-14-ci-provenance/`. Zero model turns and GitHub writes.

```text
LGCW_LIVE=1 uv run python spikes/2026-10-14-ci-provenance/probe.py
{
  "repository": "bodegus/lg-code-workflow",
  "runs_inspected": 0,
  "failed_jobs_inspected": 0,
  "runner_loss_jobs": 0,
  "observations": [],
  "model_turns": 0,
  "github_writes": 0
}
LGCW_LIVE=1 uv run python spikes/2026-10-14-ci-provenance/fixture_probe.py
repo=bodegus/family-calendar run=38441965084 job=115450536348
annotation[0].path=.github message=Process completed with exit code 1.
annotation[1].path=.github message=ubuntu-latest migration notice
service_output="\n\n"
step1=Set up job/success; step7=Audit production dependencies/failure
steps_observed=true
literal_error_command_in_downloaded_log=false
runner_loss=false
model_turns=0 github_writes=0
```

The fixture output above is trimmed, retaining fields relevant to provenance. The complete
sanitized observation is pinned in `tests/fixtures/ci/provenance-observation.json`; logs and
credentials are not committed. Real `.github` annotations occur for a user-command failure,
so the path cannot be a service authority. Numbered setup and user-step metadata is present.

Verdict: **partially confirmed; R2-F12 remains inconclusive** for real runner loss and a literal
printed `::error` command. No such run was observed, and no failure was manufactured. Carry
those two live specimens to T17 qualification if available. Runtime routing does not trust either
annotation paths or check-run output. It requires structural GitHub step/conclusion evidence,
and a failed rerun is always offered to the builder subject to the normal fix cap. This evidence
is not proof of end-to-end workflow execution or a universal GitHub guarantee.
