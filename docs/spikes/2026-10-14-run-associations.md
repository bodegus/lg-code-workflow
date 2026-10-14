# Workflow-run PR associations — 2026-10-14 UTC

## Question and expectation

Does the pinned SDK workflow-run pull_requests list name an open PR? Expect yes, as T15's
ownership filter requires the association for pull_request events. A prior read found an empty
list on the owner-approved closed T5 fixture; verify the state distinction before changing policy.

## Probe

Existing own PR5 and the D-032 closed fixture PR25 only. Public githubkit0.16.1 get-workflow-run,
existing guarded GitHubClient.get_pr and code-only GhCliTokenProvider; no token output, model
turn or GitHub write. Throwaway code/question live under gitignored spikes/2026-10-14-run-associations/.
The target fixture was already explicitly authorized by D-032; no new issue/PR/branch was made.

```text
LGCW_LIVE=1 uv run python spikes/2026-10-14-run-associations/probe.py
{
  "observations": [
    {
      "repo": "bodegus/lg-code-workflow",
      "pr": 5,
      "pr_state": "OPEN",
      "pr_head": "ed914988a1b4d12cb5e570fcdbf000fef24ce782",
      "run_id": 38488590957,
      "event": "pull_request",
      "head_sha": "ed914988a1b4d12cb5e570fcdbf000fef24ce782",
      "head_branch": "codex/t15-ci-wait",
      "pr_branch": "codex/t15-ci-wait",
      "head_repository": "bodegus/lg-code-workflow",
      "pull_requests": [
        5
      ]
    },
    {
      "repo": "bodegus/family-calendar",
      "pr": 25,
      "pr_state": "CLOSED",
      "pr_head": "617b1ea5857163dac0d239b26d91fdb97424def3",
      "run_id": 38441965084,
      "event": "pull_request",
      "head_sha": "617b1ea5857163dac0d239b26d91fdb97424def3",
      "head_branch": "lgcw-contract-3285a3b99c0f458694cd76796795de8c",
      "pr_branch": "lgcw-contract-3285a3b99c0f458694cd76796795de8c",
      "head_repository": "bodegus/family-calendar",
      "pull_requests": []
    }
  ],
  "github_writes": 0,
  "model_turns": 0
}

```

## Verdict and consequence

Confirmed for the observed OPEN case: repository, branch, exact head and PR5 association all
match. The CLOSED fixture has no association. Universality across all open GitHub runs remains
unproven; no broader guarantee is inferred from one run. No ownership-filter change follows:
ci_wait stops closed PRs before selecting runs, and its open-PR rule fails closed on missing
associations. The real T17 run must qualify its actual metadata and complete workflow separately.
