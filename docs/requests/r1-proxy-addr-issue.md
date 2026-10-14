# R1 issue proposal (executed by explicit owner delegation)

Executed as [family-calendar#26](https://github.com/bodegus/family-calendar/issues/26) after Alex
explicitly authorized the prepared issue and real test in the builder chat. The result is in
[R1 inspection](../runs/r1-proxy-addr-26.md); the following preserves the original proposal.

Original authority: owner decision relayed in PR4 comment6159291007 reserves the first live issue's
creation to Alex. This is proposed issue text, not a run report or completed acceptance.

Repository: `bodegus/family-calendar`

Title: **Fix the proxy-addr production audit failure**

```markdown
Fix the transitive proxy-addr production dependency vulnerability that currently fails the
production npm audit in CI. Use the smallest compatible dependency update that removes the
finding, and regenerate the lockfile through npm.

Acceptance criteria:
- [ ] A clean npm ci succeeds.
- [ ] npm run check succeeds.
- [ ] npm audit --omit=dev --audit-level=high exits 0.
- [ ] The existing Node 24, Node 26 and container CI jobs pass on the resulting PR head.
- [ ] The PR explains the dependency/lockfile change and contains real command output.

Keep the change bounded to the dependency fix and any necessary regression coverage.
Preserve the audit, CI checks and their assertions. Finish with a merge-ready PR; do not merge.
```

The workflow's operator will run `uv run lgcw run bodegus/family-calendar#<number>`, interrupt
once during `ci_wait`, resume, and retain the actual report, CI and side-effect receipts.
The configured review level and the prototype's light-review mapping will both be logged.
