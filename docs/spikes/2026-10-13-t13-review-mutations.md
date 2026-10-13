# T13 guard and ledger-source removal checks

Question: does removing each guard or PR-body source/dedupe rule fail a behavior assertion?
Expected: every selected mutation exits pytest with 1; collection errors (2) do not count.

This file is a retained execution transcript, not a reproducible probe distribution. Per the
running-spikes skill, the throwaway probe is gitignored and is not included in the repository.

The ignored probe copies src/ into a temporary directory without bytecode, verifies lgcw imports
that copy via PYTHONPATH, mutates one condition at a time and runs the selected unit test against
real temporary git/fake GitHub. Each mutation is restored in the copy before the next. Production
source is never changed. Credentials/live authority are not used; LGCW_LIVE is removed.

```text
$ uv run python spikes/2026-10-13-t13-mutations/probe.py
{"exit": 1, "guard": "closed_issue", "summary": "1 failed, 1 passed, 21 deselected, 255 warnings in 1.03s"}
{"exit": 1, "guard": "pr_number", "summary": "1 failed, 1 passed, 21 deselected, 255 warnings in 0.55s"}
{"exit": 1, "guard": "remote_moved", "summary": "1 failed, 22 deselected, 255 warnings in 0.79s"}
{"exit": 1, "guard": "pr_head", "summary": "1 failed, 22 deselected, 255 warnings in 0.44s"}
{"exit": 1, "guard": "journal", "summary": "1 failed, 22 deselected, 255 warnings in 0.33s"}
{"exit": 1, "guard": "message", "summary": "1 failed, 1 passed, 21 deselected, 255 warnings in 1.14s"}
{"exit": 1, "guard": "empty_diff", "summary": "1 failed, 1 passed, 21 deselected, 255 warnings in 1.06s"}
{"exit": 1, "guard": "recorded_head", "summary": "1 failed, 22 deselected, 255 warnings in 0.64s"}
{"exit": 1, "guard": "sanitize", "summary": "1 failed, 22 deselected, 255 warnings in 0.42s"}
{"exit": 1, "guard": "body_source", "summary": "1 failed, 5 deselected, 255 warnings in 0.08s"}
{"exit": 1, "guard": "run_dedupe", "summary": "1 failed, 5 deselected, 255 warnings in 0.07s"}
{"exit": 1, "guard": "body_author", "summary": "1 failed, 3 passed, 2 deselected, 255 warnings in 0.07s"}
{"exit": 1, "guard": "body_branch", "summary": "1 failed, 3 passed, 2 deselected, 255 warnings in 0.06s"}
{"exit": 1, "guard": "body_kind", "summary": "2 failed, 2 passed, 2 deselected, 255 warnings in 0.06s"}
all 14 guard/body mutations killed by behavioral assertions
```

The regressions cover closed-issue and PR-number rejection before clone creation; a foreign remote
head before PR creation; a changed PR response before publishing initial receipts; an unjournaled
PR; checkpoint message, empty diff and recorded SHA separately; token redaction on comments/body/
logs; PR-body inclusion, workflow author, branch and run-only admission; and run-copy dedupe while
preserving distinct CI rerun facts.

Verdict: all fourteen removals are detected by behavioral assertions. Source-removal logs are
/tmp/lgcw-t13-mutant-<guard>.log. This supplements the normal make check gate and does not replace
live adapter or full-workflow qualification. The new criterion tests also reject HTML placeholders
and indented code; compiled graph tests cover the actual retry/close/clone recovery defects.
