# githubkit 0.16.1 list iterator typing

Question (written in the probe before running): do explicit official model iterator types preserve
SDK pagination typing? Expected: mypy strict accepts all three list endpoints without casts or
ignores. No requests or credentials are used.

The installed SDK's wrapper returns a generic paginator, but inference at an unannotated async
loop could not establish its element type for issue comments, simple PRs and submitted reviews.
An identity map callback did not resolve the three `Need type annotation` errors. Both attempts
and their output were posted on PR #1 before changing that approach.

Probe: `spikes/2026-10-13-githubkit-pagination/probe.py` (throwaway, gitignored), on the locked
githubkit 0.16.1 / githubkit-schemas 26.9.29 environment. Each function accepts a typed SDK client,
declares `AsyncIterator` of the official `githubkit_schemas.v2026_03_10.models` record, and returns
the SDK's `rest.paginate(...)` iterator unchanged. The probe is not invoked and makes no requests.

```text
$ uv run mypy spikes/2026-10-13-githubkit-pagination/probe.py
Success: no issues found in 1 source file
exit 0
```

Verdict: confirmed. Consequence: annotate those three iterator locals using official schema types,
imported only for typing. Retain the SDK paginator; do not cast to Any, suppress diagnostics or
write another paginator. D-021 covers the SDK selection and retry ownership.
