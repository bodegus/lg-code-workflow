# Approved R2b issue: isolate dependency refresh publication

Alex approved the exact be1a3cb draft for creation and execution. It became
[family-calendar issue30](https://github.com/bodegus/family-calendar/issues/30), after Alex merged
PR29 as22446af. The run started from merged harness0a1f3c6. Authority follows [reviewer decision6168424440](https://github.com/bodegus/lg-code-workflow/issues/9#issuecomment-6168424440).
The Dependabot correction carries issue9's existing owner requirement to keep minor/major/security
updates. Credential creation remains Alex's decision and waits for the isolation fix to merge.

## Proposed title

Isolate weekly dependency refresh publication and retain non-patch Dependabot updates

## Proposed issue body

### Goal

Complete the safe weekly patch-maintenance workflow introduced by PR29. Fresh dependency code
must run in a secret-free verification job; a separate clean job may use the publication token
to propose only the verified package files. Without a token, finish successfully with an
explanatory skip. Retain ordinary minor/major and security Dependabot proposals.

### Acceptance criteria

1. Split `.github/workflows/refresh-dependencies.yml` into independent verify and publish jobs.
   Verify has only read access, checkout credentials are not persisted, and the publication
   secret never enters its environment. It refreshes within the existing tilde ranges, then
   runs npm ci, npm run check and npm audit --omit=dev --audit-level=high.
2. Publish runs on a fresh runner after successful verification. It runs no freshly installed
   dependency code, lifecycle hooks, npm install/ci, repository scripts or untrusted git hooks.
   Transfer only regular package.json/package-lock.json files and plain validation results as
   data. Do not transfer .git, executable helpers, arbitrary paths or symlinks. Validate the
   expected filenames and JSON before using the files.
3. Keep the write credential confined to publication, use least-privilege permissions and
   pinned actions, and keep the existing stable branch/one-PR behavior. Weekly Monday06:00UTC,
   main-only manual dispatch and no-change behavior remain supported. Refresh PRs must receive
   the normal CI checks when an owner-provisioned supported credential is eventually present.
4. If DEPENDENCY_REFRESH_TOKEN is absent, emit a clear notice and job summary and skip publication
   successfully. Do not create a PR, push a branch or fail merely because a credential is absent.
   Never print or provision a credential.
5. Change `.github/dependabot.yml` to suppress only npm patch version proposals; keep minor/major
   version proposals and security updates. Do not disable all npm version updates with a zero
   open-PR limit. Preserve the existing Actions and Docker update policy.
6. Update the existing README/contributor guidance only where it describes credential handling,
   missing-token behavior or the npm Dependabot policy.
7. Prove source and local behavior with actionlint, an isolated changed/no-change package refresh
   fixture, and a missing-token publication fixture that performs no write. Preserve all existing
   CI/container/audit assertions. Do not simulate a successful hosted PR publication.

lgcw-allow: .github/workflows/refresh-dependencies.yml
lgcw-allow: .github/dependabot.yml
lgcw-allow: AGENTS.md

### Verification boundary

The builder delivers and proves source/local behavior; the normal workflow gate and exact-head
CI independently validate it. Actual scheduled/manual publication is a post-merge qualification,
not a reason for a partial builder handoff. After the isolation fix merges, a manual no-token
run should show the successful skip on GitHub. Credential choice, provisioning and any later
credentialed publication test are controlled by Alex; no token may be created before that merge.
