# 07 — Review tiers, builder/reviewer context, and CI "fix or move on" without an LLM

Status: **complete** (2026-10-13). Research only — nothing installed, cloned or run; sources read with web fetch/search
and read-only `gh api`. Legend: **V** / **verified** = checked against the linked source (permalink at a tag/commit, or
docs fetched 2026-10-13); **V(abs)** = abstract only; **V2** = via a secondary summary; **V-obs** = observed on real
PRs/runs via the GitHub API; **I** / **inferred** = my reasoning. Siblings not repeated: `02-builder-reviewer-harness.md`
(Codex harness), `03-step-patterns.md` (S6 GitHub reads and classifier, S8 loop data model).

## Summary (read this first)

1. **Tiering is deterministic everywhere it runs at scale.** Meta gates the riskiest 5% / 10% / 50% of diffs by period
   and auto-approves only below P5 after path blocklists; Chromium, Kubernetes, rulesets and RADAR escalate on **paths**,
   size and history — not on an LLM's opinion. Among AI reviewers only Claude's managed review (more agents for large
   changes) and PR-Agent's `model_routing` (hunks/files → cheaper model) pick depth automatically; Copilot's
   Lite/Balanced is a human choice. → D.1: a pure-code `pick_tier` (T0–T3) from changed lines, files, path risk
   classes, dependency changes and human labels.
2. **Reviewer count:** humans gain from 1 → 2 reviewers, little from 2 → 4; LLM copies raise recall with diminishing
   returns, lenses/other families overlap less, and **precision is the binding constraint** (every production system
   adds a verify/filter step). → 1 reviewer (T1), 1–2 (T2), 3 distinct lenses (T3), verify blocking findings.
3. **Re-review must be scoped:** every unattended product that re-reviews on push limits itself to the interdiff and
   never repeats a point; full re-review + new nits is the documented loop (this repo's conductor re-reviews the full
   diff every round). Block only on P0/P1 introduced by the change (Codex's own rubric), cap rounds at 1–2.
4. **Context:** Codex's own `/review` runs in a fresh, empty-history sub-agent and writes findings back into the
   builder's thread; the forked-context variant is deprecated — consistent with the owner decision. Resuming the
   builder works, but: auto-compaction at ~245k tokens is **remote and drops all tool outputs and assistant messages**
   (keeps ≤ 64k of user messages); per-turn overrides are sticky; cached input is 10% (5% on GPT-6.1 Sol) of fresh input
   on the published credit card, but a resume after > 30 min is probably cold. → restate the findings ledger in every
   fix prompt; restart from a handoff after two failed attempts or at ~60% context.
5. **Handoff:** the builder returns a typed `BuildHandoff` (summary, approach, decisions, assumptions, acceptance
   evidence, files, tests, not-done, risks, dispositions); code renders the PR body (this repo's template) and the
   reviewer packet (facts + decisions as claims to verify; no self-grades, no transcript).
6. **CI:** platforms classify failures deterministically (runner/annotation strings, exit codes, same-SHA fail→pass,
   "also red on base"); coding agents mostly let an LLM decide. → D.4: an 11-row table with rerun caps per head and per
   PR. Correction for `03`: a job **timeout ends `cancelled`**, distinguishable only by its annotation.

## Contents
- A. Risk-based review tiering (A.1 orgs, A.2 products, A.3 signals, A.4 reviewer-count evidence, A.5 re-review scope, A.6 severity)
- B. Context between builder and reviewer (B.1 Codex reviewer, B.2 resuming one thread, B.3 evidence, B.4 handoff templates)
- C. CI "fix or move on" without an LLM (C.1 signals, C.2 signatures, C.3 flaky, C.4 pre-existing, C.5 bots)
- D. Recommendations (D.1 tier rubric, D.2 context plan, D.3 handoff schema, D.4 S6 decision table)
- E. Open questions and cheap experiments

---

## A. Risk-based review tiering

Sources fetched 2026-10-13. Load-bearing items (Meta DRS gates, RADAR, GitLab follow-up rules, Claude Code Review
statistics, Copilot effort levels, CodeRabbit defaults, PR-Agent config, GraphQL resolution enum) were re-checked
by me after the research pass.

### A.1 How production organisations decide how much review a change gets

| Org / system | Mechanism | Numbers | Evidence |
|---|---|---|---|
| **Meta — Diff Risk Score (DRS)** | Fine-tuned Llama predicts whether a diff will cause a SEV; used in ~19 "risk-aware" features (code-freeze gating, reviewer selection, test selection, release risk). | 10,000+ diffs landed during a 2024 freeze that would previously have been blocked. | **V** [engineering.fb.com 2025-08-06](https://engineering.fb.com/2025/08/06/developer-tools/diff-risk-score-drs-ai-risk-aware-software-development-meta/) |
| Meta — gating policy (paper) | Percentile gates that move with context: block the riskiest **5%** on weekends, **10%** in "yellow" periods, **50%** in "red" periods (e.g. Black Friday); authors can escalate with a justification. Logistic-regression baseline features: added/deleted lines relative to file size, new file, number of files, prior authors, **previous SEV in the file/folder**, high-criticality service, complexity, language, author created the file, author's landed diffs. | Baseline catches 18.7% / 27.9% / 84.6% of SEVs at 5% / 10% / 50% gating. | **V** [arXiv 2410.06351 (Meta, 2024-10-08)](https://arxiv.org/html/2410.06351v1) |
| Meta — **RADAR** (auto-approval of the safest diffs) | Funnel: eligibility gates (not SOX-scoped, not marked as needing extra review, no **file-path blocklist** hit, author criteria) → static heuristics → DRS percentile → LLM review (must report ≥ 8/10 confidence, any risk signal disqualifies) → deterministic validation → land. Any failure → normal human review. Human diffs only below **P5**, bot diffs P20, allow-listed runbooks P50. | 535K+ diffs reviewed, 331K+ landed; revert rate ~⅓ and incident rate 1/50 of non-RADAR diffs; 60.31% approve rate at P50. | **V** [arXiv 2605.30208 v2 (2026-06-12)](https://arxiv.org/abs/2605.30208) |
| **Google** | Every change needs LGTM + OWNERS + readability approval (one person can give all three); most reviews have one reviewer. Small changes encouraged: ~100 lines reasonable, 1,000 usually too large; reviewer may reject for size alone. Non-blocking comments are prefixed `Nit:` / `Optional:` / `FYI:`; "LGTM with comments" is normal. | Sadowski et al. 2018 (~9M changes): median 24 changed lines, ~90% touch < 10 files, median **1** reviewer and < 25% have more (**V** [PDF](https://sback.it/publications/icse2018seip.pdf)). | **V** [SWE at Google ch. 9](https://abseil.io/resources/swe-book/html/ch09.html), [eng-practices: standard](https://google.github.io/eng-practices/review/reviewer/standard.html), [comments](https://google.github.io/eng-practices/review/reviewer/comments.html), [small CLs](https://google.github.io/eng-practices/review/developer/small-cls.html) |
| Google — automated comments | Tricorder analyzers must keep **< 10% effective false positives** (platform just under 5%); noisy analyzers are disabled; only newly introduced warnings shown. ML-resolved comments tuned to 50% target precision. AutoCommenter moved from one global threshold to **per-best-practice thresholds**, restricted posting to **changed lines** (80% of raw comments hit unchanged code), and suppressed 17 non-actionable practices (usefulness 54% → 66%). | | **V** [ch. 20](https://abseil.io/resources/swe-book/html/ch20.html), [Google Research 2023](https://research.google/blog/resolving-code-review-comments-with-ml/), [arXiv 2405.13565](https://arxiv.org/html/2405.13565v1) |
| **Path-based mandatory review** | Chromium: `per-file *.mojom=set noparent` + `file://ipc/SECURITY_OWNERS`; Kubernetes: API type/validation changes need the `api-review` label and the implementation review covers only differences from the approved design; Mozilla: sec-approval only for sec-high sandbox escapes; GitHub rulesets: required reviewers per file pattern; OpenStack: usually two core +2, a −2 is sticky across patch sets. | | **V** [chromium url/mojom/OWNERS](https://github.com/chromium/chromium/blob/9cd4b9f5fcc8e08ebd360f086b07f839682e982a/url/mojom/OWNERS#L1-L4), [k8s api-review L53-L108](https://github.com/kubernetes/community/blob/810850f95921c56e697eb7bf73f1e3d4b2b458a9/sig-architecture/api-review-process.md#L53-L78), [Mozilla](https://firefox-source-docs.mozilla.org/bug-mgmt/processes/security-approval.html), [rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets), [OpenStack](https://docs.openstack.org/project-team-guide/review-the-openstack-way.html) |
| **Uber uReview** | Three assistants (bugs, best practices, AppSec); a grader sets confidence thresholds **per assistant, language and comment category**; semantic dedup; low-value categories suppressed (readability nits, logging tweaks, low-impact perf, style); config/generated/experimental dirs excluded. | >90% of ~65K weekly diffs; 75% rated useful; 65% addressed (vs 51% for human comments). | **V** [Uber blog 2025-08-12](https://www.uber.com/us/en/blog/ureview/) |
| **Microsoft** | AI reviewer auto-added on PR creation; comments carry a category. | >90% of PRs, 600K+ PRs/month; 10–20% faster median completion. | **V** [devblogs 2025-07-14](https://devblogs.microsoft.com/engineering-at-microsoft/enhancing-code-quality-at-scale-with-ai-powered-code-reviews/) |
| **Atlassian RovoDev** | LLM judge for factual correctness, then a ModernBERT **actionability** filter (biggest effect in ablation). | 2.1 comments/PR; 38.7% lead to code changes; PR cycle time −30.8%. | **V** [arXiv 2601.01129](https://arxiv.org/html/2601.01129v2) |
| **ByteDance BitsAI-CR** | Rule checker + review filter; weekly rule retirement on precision and "outdated rate". | Precision ~60% → 75% with the filter; Go outdated rate 26.7%. | **V** [arXiv 2501.15134](https://arxiv.org/html/2501.15134) |

### A.2 AI reviewer products — the knobs that set depth, scope and severity

| Product | Depth / tier knob | Scope on new pushes | Severity / noise control | Evidence |
|---|---|---|---|---|
| **CodeRabbit** | `reviews.profile` `quiet \| chill (default) \| assertive` ("assertive" may feel nitpicky); `path_instructions`, `path_filters`; `estimate_code_review_effort` 1–5 | `auto_incremental_review: true` (re-review each push, commits since last review); **`auto_pause_after_reviewed_commits: 5`**; `@coderabbitai full review` on demand | findings typed Nitpick / Potential issue / Refactor, severity Critical > Major > Minor > Trivial; `request_changes_workflow` (default off); pre-merge checks `off\|warning\|error` | **V** [schema.v2.json](https://coderabbit.ai/integrations/schema.v2.json), [config docs](https://docs.coderabbit.ai/reference/configuration), [findings](https://docs.coderabbit.ai/change-stack/findings) |
| **PR-Agent** (now `The-PR-Agent/pr-agent`, v0.47.0) | **`[model_routing]` rules by `max_hunks`/`max_files` → cheaper model for small PRs** (deterministic size tiering, off by default; the shipped example routes ≤ 3 hunks to `gpt-5.6-luna` and ≤ 15 hunks / ≤ 6 files to `gpt-5.6-terra`, re-checked); effort label "Review effort x/5"; `require_security_review`, `require_tests_review` | `handle_push_trigger=false` by default; `/review -i` incremental since last review | **`num_max_findings = 3`**, findings need a realistic trigger scenario; `persistent_finding_state` + `max_previous_findings_chars = 8000` (keeps wording, skips human-resolved threads); suggestion scores ≥ 9 High, ≥ 7 Medium | **V** [configuration.toml @v0.47.0](https://github.com/The-PR-Agent/pr-agent/blob/v0.47.0/pr_agent/settings/configuration.toml#L504-L512), [reviewer prompt L99-L123](https://github.com/The-PR-Agent/pr-agent/blob/v0.47.0/pr_agent/settings/pr_reviewer_prompts.toml#L99-L123) |
| **GitHub Copilot code review** | Effort levels **Lite** (routine changes) and **Balanced** (higher-reasoning model for larger, complex or sensitive changes); chosen per request / repo / org — **no automatic selection from PR traits** | Reviews once unless the ruleset enables "Review new pushes"; may repeat earlier comments even if resolved | Since 2026-09-01 an approval assessment; approval can count only for allowed paths; resolution reasons Addressed / Won't fix / Incorrect; skips manifests and lockfiles | **V** [GA 2026-08-07](https://github.blog/changelog/2026-08-07-copilot-code-review-effort-levels-are-generally-available/), [docs](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/copilot-code-review), [approve 2026-09-01](https://github.blog/changelog/2026-09-01-copilot-code-review-can-now-approve-pull-requests/) |
| **GitLab Duo Code Review Flow** (GA 18.8) | `.gitlab/duo/mr-review-instructions.yaml` `{name, fileFilters, instructions}` appended to defaults | New review on push on by default (19.5+); **comments only on lines added after its last commented commit**, except correctness problems (bug, security, data loss) anywhere | **never repeats a point from an earlier thread, even if resolved**; approves when it has nothing to say, else requests changes | **V** [flow docs](https://docs.gitlab.com/user/duo_agent_platform/flows/foundational_flows/code_review/), [instructions](https://docs.gitlab.com/user/gitlab_duo/customize_duo/review_instructions/) |
| **OpenAI Codex review** | `review_model`; rules in `AGENTS.md` (root + nested) | `/review` targets: uncommitted, base branch, commit, custom | **Only P0/P1 posted on GitHub**; rubric drops pre-existing bugs and nits (B.1) | **V** [GitHub docs](https://learn.chatgpt.com/docs/third-party/github), rubric (B.1) |
| **Claude Code Review (managed)** | Depth scales with size (more agents for large changes, light pass for trivial) | Once / every push (auto-resolves fixed threads) / manual | 🔴 Important, 🟡 Nit, 🟣 Pre-existing; check run always neutral with machine-readable counts for your own gate; `REVIEW.md` can cap nits and tell re-reviews to drop new nits after round 1 | **V** [docs](https://code.claude.com/docs/en/code-review); [blog 2026-03-09](https://claude.com/blog/code-review): PRs > 1,000 lines 84% get findings (avg 7.5), < 50 lines 31% (avg 0.5), < 1% marked incorrect, $15–25 and ~20 min per review |
| **Claude Code `code-review` plugin** | Haiku gate skips closed/draft/trivial/already-reviewed PRs; 4 parallel reviewers; **each finding validated by its own subagent** | — | 2025: drop findings < 80/100; 2026: "high signal only", explicit false-positive list (pre-existing, pedantic nits, linter-catchable) | **V** [@b85cc44 L20-L26](https://github.com/anthropics/claude-code/blob/b85cc4474f22c23d540363fe842889420339bddb/plugins/code-review/commands/code-review.md#L20-L26), [@db8834b L14-L86](https://github.com/anthropics/claude-code/blob/db8834ba1d72e9a26fba30ac85f3bc4316bb0689/plugins/code-review/commands/code-review.md#L14-L86) |
| **Cursor Bugbot** | `.cursor/BUGBOT.md` collected upward from changed files | every update / once per PR / on mention | check is neutral unless fail-on-unresolved; **Autofix max 3 attempts per PR** to prevent loops | **V** [docs](https://cursor.com/docs/bugbot) |
| **Graphite Agent** | custom rules (prompt, regex, glob-scoped), exclusions, `linguist-generated` | not documented | vendor claim < 3% false positives; 2023 lesson: a 5%-FP regex rule on a rare violation gave ~50/50 odds per flag and destroyed trust | **V** [customization](https://graphite.com/docs/ai-review-customization), [experiments 2023-10-30](https://graphite.com/blog/ai-code-review-experiments) |
| **Open SWE reviewer** (v2) | risk_score 1–5 rubric in optional approval assessment | **re-review only since `last_reviewed_sha`**, reconcile open findings, skip anything already in a PR thread | `severity low…critical`, `confidence`, in-diff only, `update_finding(resolved)` / `dismissed` with a note posted as the reply | **V** (A.2.1 below) |

#### A.2.1 Open SWE reviewer details (my direct read, `langchain-ai/open-swe` @ `0942b415`)
- Re-review prompt: given previous reviewed SHA and new head, review **only the changes since the previous reviewed
  SHA**, reconcile each open finding, add only net-new findings from that range, and skip anything already covered by
  an existing PR review thread (bot or human). **verified**
  [rereview-context.md.jinja L1-L23](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/resources/prompts/reviewer/rereview-context.md.jinja)
- Reconciliation verbs: `update_finding(id, status="resolved", note)` when code fixed it;
  `resolve_finding_thread(finding_id, status="dismissed", note)` when a human reply proves it invalid; the note is
  posted as the GitHub reply; a re-review with nothing new is reported as `skipped_empty_re_review` (no review posted).
  **verified** [reviewer/main.md.jinja L18-L23](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/resources/prompts/reviewer/main.md.jinja#L18-L23)
- `add_finding`: `severity ∈ {low, medium, high, critical}`, `confidence ∈ {low, medium, high}`, free-form `category`
  (correctness, security, perf, style, …), lines **must be inside the PR diff** (out-of-diff findings rejected),
  `suggestion` only for fixes of ≤ 4 lines. **verified**
  [tools/add_finding.md L13-L51](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/resources/prompts/tools/add_finding.md#L13-L51)
- Optional approval assessment from `.open-swe/APPROVALS.md`: `risk_score` 1–5 (1 trivial/docs-only, 2 small
  well-understood, 3 meaningful behavioural impact, 4 sensitive or broad, 5 critical/known severe defects),
  `decision ∈ {would_approve, needs_human_review}`; "Unresolved findings always require human review"; on re-review
  the assessment must cover earlier changes and outstanding findings, not just the latest diff. **verified**
  [approval-assessment.md.jinja L1-L15](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/resources/prompts/reviewer/approval-assessment.md.jinja)


### A.3 Deterministic signals for picking a tier, and published thresholds

| Signal | Production use (evidence) | Published numbers |
|---|---|---|
| **Paths touched** | Chromium SECURITY_OWNERS, Kubernetes `api-review`, GitHub rulesets path reviewers, Meta RADAR path blocklists / SOX scope, Copilot approval limited to allowed paths (A.1, A.2) | rulesets: up to 15 teams per pattern, 0–10 approvals |
| **Size** | Google eng-practices; Meta features; PR-Agent `model_routing`; Claude managed review depth; Kubernetes Prow `size/*` labels | Google ~100 lines fine / 1,000 too large; SmartBear/Cisco study (2,500 reviews): < 200, never > 400 LOC per review, < 300–500 LOC/h (**V2** [summary](https://mikeconley.ca/blog/2009/09/14/smart-bear-cisco-and-the-largest-study-on-code-review-ever/)); Prow: XS 0–9, S 10–29, M 30–99, L 100–499, XL 500–999, XXL 1000+ (additions + deletions, generated files skipped) — **V** [prow size.go L36-L76, L131-L132 @b4d923a](https://github.com/kubernetes-sigs/prow/blob/b4d923a1a60cedd794f9461c529df11ebd8e1abc/pkg/plugins/size/size.go#L36-L76); finding rate rises with size: 31% of < 50-line PRs vs 84% of > 1,000-line PRs get findings (Claude) |
| **History of touched files** | Meta "previous SEV in the file/folder"; JIT defect prediction | Kamei et al. 2013 (IEEE TSE, 11 projects): change-level models 68% accuracy / 64% recall; 20% of inspection effort finds 35% of defect-inducing changes — **V** [record](https://kyushu-u.elsevierpure.com/en/publications/a-large-scale-empirical-study-of-just-in-time-quality-assurance/). Feature groups: diffusion (subsystems, dirs, files, entropy), size (lines added/deleted, file size), purpose (bug fix), history (developers, age, prior changes), experience — **I** (paper not re-read; DRS-OSS replication uses the same 12-ish metrics, **V** [arXiv 2511.21964](https://arxiv.org/html/2511.21964v2)) |
| **Author / source** | RADAR stricter for humans (P5) than bots (P20) and for AI codemods than deterministic codemods; GitHub ruleset "additional approval for unattributed Copilot PRs" on by default | — |
| **Generated / vendored / lockfiles** | Excluded from AI review by Copilot, Uber, Graphite (`linguist-generated`), PR-Agent, Prow size | — |
| **Dependency changes** | deterministic gate, e.g. `actions/dependency-review-action` (`fail-on-severity`, `deny-packages`, `deny-licenses`) | **V** [action.yml](https://github.com/actions/dependency-review-action/blob/main/action.yml) |
| **Labels** | CodeRabbit `auto_review.labels` (with `!`), Kubernetes `/label api-review`, PR-Agent `ignore_pr_labels` | — |
| **Context / calendar** | Meta weekend / yellow / red periods | 5% / 10% / 50% gated |
| **Round count** | CodeRabbit auto-pause after 5 reviewed commits; Bugbot Autofix ≤ 3 attempts | — |

Cheap deterministic "lenses" that can run before (or instead of) an LLM lens on a risk class (**V** existence and
scope; use is **I**): GitHub Actions — `zizmor` v1.30.1 (audits such as `dangerous-triggers`, `template-injection`,
`excessive-permissions`, `unpinned-uses`, `cache-poisoning`, `secrets-inherit`; [docs](https://docs.zizmor.sh/audits/));
secrets — `gitleaks`; Dockerfiles — `hadolint`; shell — `shellcheck`; Ansible — `ansible-lint`; dependencies —
`dependency-review-action`. This repo's `lint` stage runs only `ruff` and `yamllint`
([ops/ci.sh L83-L87 @5f89337](https://github.com/bodegus/openclaw2-deploy/blob/5f893376dde7da354f428232e3855e75042799fd/ops/ci.sh#L83-L87)).

### A.4 How many reviewers, which lenses, which model family — evidence

Legend: **V** checked against the linked source; **V(abs)** abstract only; **I** inferred. Items I re-checked myself
after the research pass: SWR-Bench, Song 2026, OpenAI code-verification post, Claude Code best practices, Debugging
Decay Index.

**Humans — 1 → 2 reviewers helps, 2 → 4 mostly adds cost; expertise beats headcount**

| Study | Setup | Result | Evidence |
|---|---|---|---|
| Porter, Siy, Toman & Votta, IEEE TSE 1997 | 18-month randomised experiment at Lucent, 88 inspections, teams of 1 / 2 / 4 | 2- and 4-person teams found the same defect density, both better than 1; effort grew with every reviewer; only 13% of issues logged in preparation were real defects | **V** [PDF](https://users.ece.utexas.edu/~perry/education/SE-Intro/porter-tse23.pdf) |
| Rigby & Bird, ESEC/FSE 2013 | Android, Chromium OS, Bing, Office, SQL Server, AMD | median **2** active reviewers everywhere; Microsoft invites 3–4 but 2 take part; comments rise only minimally with more reviewers | **V** [PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/rigby2013convergent.pdf) |
| Rigby, German, Cowen & Storey, TOSEM 2014 | 6 OSS projects | doubling reviewers → +45.6% issues discussed (sublinear); doubling churn 17 → 34 lines → +12% | **V** [PDF](https://users.encs.concordia.ca/~pcr/paper/Rigby2014TOSEM.pdf) |
| Sadowski et al., ICSE-SEIP 2018 | Google, ~9M changes | median **1** reviewer, < 25% have more; owners/readability + static analysis carry part of the load | **V** [PDF](https://sback.it/publications/icse2018seip.pdf) |
| Bosu, Greiler & Bird, MSR 2015 | Microsoft, 1.5M comments | 64–68% useful; usefulness falls with files per change; reviewers who had reviewed the file before: 65–71% useful vs 32–37% for first-timers | **V** [PDF](https://www.amiangshu.com/papers/CodeReview-MSR-2015.pdf) |
| Edmundson et al., ESSoS 2013 | 30 developers, PHP app with 7 known vulnerabilities | nobody found all 7; ~10 independent reviewers for 80% chance of finding all, ~15 for 95% | **V** [PDF](https://people.eecs.berkeley.edu/~daw/papers/coderev-essos13.pdf) |
| Basili et al. EMSE 1996 vs Regnell et al. EMSE 2000 | perspective-based reading (tester / designer / user) | lenses beat usual methods at NASA; replication found no difference between perspectives — mixed | **V** [PDF](https://www.cs.umd.edu/~mvz/handouts/emp_pbr.pdf) / **V(abs)** [Springer](https://link.springer.com/chapter/10.1007/978-3-642-29044-2_13) |
| McIntosh et al. MSR 2014; Kononenko et al. ICSME 2015 | Qt/VTK/ITK; Mozilla | low coverage/participation ↔ more post-release defects; 54% of reviewed Mozilla changes still introduced bugs, predicted by patch size, files, reviewer load | **V(abs)** [McIntosh](https://rebels.cs.uwaterloo.ca/confpaper/2014/05/30/the-impact-of-code-review-coverage-and-code-review-participation-on-software-quality.html), **V** [Kononenko](https://plg.uwaterloo.ca/~migod/papers/2015/icsme15-OleksiiOlgaLatifa.pdf) |

**LLM reviewers — copies raise recall, lenses/families overlap less, precision is the binding constraint**

| Source | Result | Evidence |
|---|---|---|
| SWR-Bench (arXiv 2509.01494 v2; 500 PRs with verified issues + 500 clean) | best single tool 19.4% F1 at 16.7% precision; running the same reviewer n times and merging ("self-aggregation") raised Gemini-2.5-Flash recall 13.9% → 30.4% and F1 15.3% → 21.9% at n = 10; n = 5 already beat one Gemini-2.5-Pro pass | **V** [arXiv](https://arxiv.org/html/2509.01494v2) |
| Cursor "Building a better Bugbot" (2026-01-15, vendor) | first design: 8 parallel passes with shuffled diff, keep bugs seen by ≥ 2 passes (vote to cut false positives); later agentic redesign raised fix rate of flagged bugs 52% → 70%+ | **V** [blog](https://cursor.com/blog/building-bugbot) |
| Debate vs voting (Huang et al. ICLR 2024; Smit et al. ICML 2024; Choi et al. NeurIPS 2025) | at equal compute, multi-agent debate does not beat self-consistency / majority vote | **V** [2310.01798](https://arxiv.org/html/2310.01798), [Smit](https://proceedings.mlr.press/v235/smit24a.html), **V(abs)** [2508.17536](https://arxiv.org/abs/2508.17536) |
| Lenses: iCodeReviewer (Huawei, arXiv 2510.12186); ChatEval (2308.07201) | security "expert" prompts routed by code features: recall 62.7% vs 43.3% at equal precision; ChatEval: same-role judges = single judge (53.8%), different roles 60.0%; personas alone add nothing (Zheng et al. EMNLP Findings 2024) | **V** [iCodeReviewer](https://arxiv.org/html/2510.12186), [ChatEval](https://arxiv.org/html/2308.07201), **V(abs)** [personas](https://aclanthology.org/2024.findings-emnlp.888/) |
| Correlated errors (Kim et al. ICML 2025; Goel et al. 2025) | across 350+ LLMs, when two models are both wrong they agree on the same wrong answer ~60% of the time; more capable models are more correlated, across providers | **V(abs)** [2506.07962](https://arxiv.org/abs/2506.07962), [2502.04313](https://arxiv.org/abs/2502.04313) |
| Song 2026 (arXiv 2610.01471 v2, single author; 150 planted errors, 900 sessions) | a fresh same-model review and a top-tier other-family review: no significant F1 difference, but they find partly different errors (Jaccard 41.2%); fresh same-model + other-family found 56.7% vs 42.7% for two same-model reviews (p = .006); a lightweight other-family reviewer was no better | **V** [arXiv](https://arxiv.org/abs/2610.01471) — directional |
| Xiang et al. 2026 (KDD workshop, arXiv 2607.21656) | cross-review direction matters: Claude reviewing Codex drafts 71.6% → 89.7% pass, Codex reviewing Claude drafts 91.4% → 82.8% (worse) | **V(abs)** [arXiv](https://arxiv.org/abs/2607.21656) — directional |
| c-CRAB (arXiv 2603.23448; 184 PRs, test-backed review items) | Claude Code 32.1%, Devin 24.8%, PR-Agent 23.1%, Codex 20.1%; all four combined 41.5% | **V** [arXiv](https://arxiv.org/html/2603.23448) |
| OpenAI "scaling code verification" (2025-12-01) | Codex generator and reviewer are the **same model** trained differently; reviewer recall on known issues is consistently **higher on human-written than on Codex-written code** (a shift in verification difficulty); 52.7% of comments led to code changes; they trade some recall for signal | **V** [post](https://alignment.openai.com/scaling-code-verification/) |
| Precision filters (BitsAI-CR; real-PR difficulty) | a second filtering pass: precision 57.0% → 65.6%, recall 45.5% → 39.8%; models score F1 0.066 on real PRs vs 0.847 on synthetic mutations, diff size the strongest predictor | **V** [2501.15134](https://arxiv.org/html/2501.15134v1), **V(abs)** [2606.15689](https://arxiv.org/abs/2606.15689) |

**Implications for the rubric** (**I**):
1. **One** strong fresh reviewer + deterministic gates is the default (Google median 1; Porter: the first reviewer is
   the big step). A **second** reviewer only on risk or size (Rigby: sublinear gains). A **third** only for high-risk
   classes — and as a different lens or a deterministic scanner, not another copy.
2. Extra reviewers should be **lenses with concrete scope** (security with a CWE/path checklist; tests: "does every
   acceptance criterion have a test that would fail without the change?"), not personas and not copies. Copies are a
   recall dial (merge) or a precision dial (vote ≥ 2 of k); skip debate.
3. Every extra reviewer adds false positives → keep a **verify** step for blocking findings (D.1 rule 1).
4. Codex reviewing Codex has a measurable blind spot (OpenAI's own data); a different family helps **only if it is at
   least as strong** (Song, Xiang). Candidate for the T3 security lens if a second login is acceptable (E.5); otherwise
   compensate with deterministic scanners.
5. Security is the outlier (Edmundson): no number of LLM copies replaces `zizmor`/`gitleaks`/`dependency-review`-style
   tools on the risky paths.
6. Vendor benchmarks disagree (e.g. Greptile 82% in its own run vs 45%/45% in Augment's run of the same repos —
   **V** [Greptile](https://www.greptile.com/benchmarks), [Augment](https://www.augmentcode.com/blog/we-benchmarked-7-ai-code-review-tools-on-real-world-prs-here-are-the-results));
   measure on our own PRs (finding acceptance per tier/lens, overlap between lenses).

### A.5 Re-review scoping after a fix round

| System | Scope after new commits | Earlier findings | Evidence |
|---|---|---|---|
| CodeRabbit | commits since last review (default); `full review` on request | statuses open / addressed / superseded; auto-pause after 5 reviewed commits | **V** (A.2) |
| PR-Agent | `/review -i` commits since last review; push trigger off by default | previous findings fed back (8,000 chars) so wording is kept and resolved threads skipped; resolve/reopen only on full runs | **V** (A.2) |
| GitLab Duo flow | only lines added since its last commented commit; correctness issues anywhere | never repeats a point, even if resolved; does not resolve old threads; a reply explaining why the code is right stops the point | **V** (A.2) |
| Open SWE | only `last_reviewed_sha..head`; reconcile each open finding; skip points already in any PR thread | `resolved` / `dismissed` + note | **V** (A.2.1) |
| Claude managed | fresh review per push (if enabled) | auto-resolves fixed threads; `REVIEW.md` can drop new nits after round 1 | **V** (A.2) |
| Copilot | full review on each push only if enabled | may repeat resolved/downvoted comments; approval dismissed on push | **V** (A.2) |
| Gerrit / Kubernetes | interdiff between patch sets; API implementation review covers only differences from the approved design | votes copied for trivial rebases / no code change (`copyCondition`) | **V** [Gerrit labels](https://gerrit-review.googlesource.com/Documentation/config-labels.html), [k8s L108](https://github.com/kubernetes/community/blob/810850f95921c56e697eb7bf73f1e3d4b2b458a9/sig-architecture/api-review-process.md#L108) |
| This repo's conductor today | **full** `git diff <base>..<head>` re-review every round; up to 3 review rounds; stop after second failed attempt at the same issue | every finding needs a disposition | **V** [review-cycle.md L77-L87, L120-L125 @5f89337](https://github.com/bodegus/openclaw2-deploy/blob/5f893376dde7da354f428232e3855e75042799fd/agents/active/conductor/skills/review-cycle.md#L77-L87) |

Reading (**inferred**): the products that run unattended on every push all narrow the re-review to the interdiff and
suppress repeats; only Copilot does full re-reviews by default and documents that it repeats itself. The anecdotes of
"every fix commit gets a fresh Minor" (CodeRabbit users, e.g. [rig#153](https://github.com/Sumit1993/rig/issues/153))
are exactly our expensive loop.

### A.6 Severity thresholds, nit-loop avoidance, round caps

- **What blocks:** Codex — only P0/P1 posted on GitHub; Claude managed — only 🔴 Important, check stays neutral and you
  gate on counts; GitLab — request changes from the flow; Bugbot — neutral unless configured; Google — `Nit:` /
  `Optional:` / `FYI:` never block, LGTM-with-comments is normal. (**V**, A.1–A.2)
- **Precision bars:** Meta LLM review ≥ 8/10 confidence; Claude plugin ≥ 80/100 then per-finding validation; Uber
  per-category thresholds; Google < 10% effective false positives; PR-Agent max 3 findings. (**V**)
- **Explicit caps:** Bugbot Autofix 3 attempts/PR; CodeRabbit pause after 5 reviewed commits; Claude `REVIEW.md`
  patterns "at most five nits" and Important-only after round 1. (**V**)
- **Loop recipe to avoid:** full re-review on every push while new nits are allowed (Copilot documents repeats;
  CodeRabbit anecdotes). (**V**/**I**)
- Codex rubric's own definitions (P0 drop everything … P3 nice to have; ignore pre-existing and style; overall
  correctness ignores nits) give us a ready-made, model-native severity contract (B.1).

---

## B. Context between builder and reviewer

**Owner decision (2026-10-13), taken as given below:** the reviewer does **not** start from the builder's context
(no fork); CI-fix and review-fix rounds **resume the builder's own Codex thread**. So this section covers (B.1) the
Codex facts that back the fresh-reviewer choice, briefly; (B.2) the mechanics and limits of resuming one Codex thread
across several fix rounds; (B.3) the short evidence on self-review vs independent review; (B.4) the handoff the
builder must return for a fresh reviewer and for the PR description.

Codex source read at `rust-v0.162.1` = commit `092d3acd` (2026-10-09; Python SDK `openai-codex` 0.162.x). Permalink
base `https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/`.

### B.1 Codex's own reviewer is fresh-context (backs the owner decision)

| Fact | Evidence |
|---|---|
| `review/start {threadId, target, delivery}`; `delivery` = `inline` (default) or `detached`; targets `uncommittedChanges`, `baseBranch{branch}`, `commit{sha,title}`, `custom{instructions}`. | **verified** [v2/review.rs L8-L67](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/review.rs#L8-L67) |
| An inline review runs a one-shot sub-agent with **empty history** (`initial_history: None` → `InitialHistory::New`), the review rubric as base instructions, web search and multi-agent tools off, approval `never`, model = `review_model` or the session model. | **verified** [tasks/review.rs L99-L143](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tasks/review.rs#L99-L143), [codex_delegate.rs L81](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/codex_delegate.rs#L81) |
| Tests pin it: `review_input_isolated_from_parent_history`; and `review_history_surfaces_in_parent_session` (findings are written back into the builder's thread so a later turn can fix them). | **verified** [core/tests/suite/review.rs L1121-L1127, L1303-L1306](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/tests/suite/review.rs#L1121-L1127), [tasks/review.rs L210-L272](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tasks/review.rs#L210-L272) |
| The forked-context variant (`detached`, a sub-agent forked from the parent's full history) is **deprecated**; the server suggests `thread/start` + inline review, or `thread/fork` + your own review turn. Reason not stated (code comments cite paginated-history limits). | **verified** [turn_processor.rs L340-L358, L1464-L1472](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server/src/request_processors/turn_processor.rs#L340-L358), [thread_manager.rs L1171-L1175](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/thread_manager.rs#L1171-L1175) |
| Reviewer rubric: flag only discrete, actionable bugs **introduced by the change** (pre-existing bugs not flagged); no speculative breakage without naming the affected code; ignore trivial style; `[P0]..[P3]` + numeric `priority`; `overall_correctness` ignores style/typos/docs/nits; `code_location` must overlap the diff; output `findings[{title, body, confidence_score, priority, code_location{absolute_file_path, line_range}}]`, `overall_correctness`, `overall_explanation`, `overall_confidence_score`. | **verified** [prompts/templates/review/rubric.md L12-L19, L34-L62, L67-L95](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/prompts/templates/review/rubric.md#L12-L19) |
| The Python SDK has **no public `review_start`**; raw JSON-RPC is reachable only through the private `Codex._client.request(...)`. | **verified** [sdk/python/src/openai_codex/client.py L327-L366](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/sdk/python/src/openai_codex/client.py#L327-L366) |

Practical reading (**inferred**): implement S7 as a fresh `thread_start(sandbox=Sandbox.read_only,
approval_mode=deny_all)` + `run(prompt, output_schema=ReviewVerdict)` whose instructions reuse the rubric above (same as
sibling `02` §4.1). A read-only sandbox "only permits reading files"
([read_only.md](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/prompts/templates/permissions/sandbox_mode/read_only.md)),
so the reviewer should rely on S4/CI test evidence rather than run tests that write caches.

### B.2 Resuming one Codex thread across several fix rounds — mechanics and limits

**B.2.1 API surface**
- `Codex.thread_resume(thread_id, *, approval_mode, base_instructions, developer_instructions, model, sandbox, config, ...)`
  reloads the thread from `CODEX_HOME` (rollout on disk) in a new app-server process. **verified**
  [api-reference.md L72](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/sdk/python/docs/api-reference.md#L72),
  [v2/thread.rs L340-L430](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L340-L430).
- Per-turn overrides are **sticky**: `cwd`, `approvalPolicy`, `sandboxPolicy`, `model`, `effort`, `summary` apply to
  "this turn and subsequent turns"; only `outputSchema` is per-turn. The SDK says the same for `sandbox=`. Set them
  explicitly on every builder turn. **verified** [v2/turn.rs L219-L272](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L219-L272),
  [api-reference.md L258](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/sdk/python/docs/api-reference.md#L258).
  (The docs page describes `approvalPolicy` as per-turn only; the source says sticky.)
- Inputs for a fix round: plain text (a **user message**) or `ExternalMessage` (sent as `turn/start.toolOutput` and
  stored as a `functionCallOutput` item with tool-level authority, for untrusted text). An `ExternalMessage` must be the
  **whole** input of a `run`/`turn`; it starts a turn when the thread is idle or **joins the active turn**. A fix round
  that needs both a trusted instruction and an untrusted log therefore either (a) starts the turn with the user message
  and passes the `ExternalMessage` to join it, (b) appends the user message with `thread/inject_items` (raw JSON-RPC,
  not in the SDK; it appends items without starting a turn) and then runs the `ExternalMessage`, or (c) puts both in
  one user message with the untrusted text fenced as data. **verified** [api-reference.md "ExternalMessage" L309-L340](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/sdk/python/docs/api-reference.md#L309-L340),
  [_inputs.py L96-L103](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/sdk/python/src/openai_codex/_inputs.py#L96-L103),
  [v2/turn.rs L153-L160](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L153-L160),
  [v2/thread.rs L1707-L1712](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L1707-L1712).

**B.2.2 Context growth**
- Bundled model catalog: every listed model (`gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-*`,
  `gpt-5.5`) has `context_window` **272,000** tokens (`max_context_window` 872,000 on GPT-6.x — presumably an
  opt-in, not checked) and a tool-output `truncation_policy` of **10,000 tokens**: each stored tool output (test run,
  file read, log) is capped at ~10k tokens (`tool_output_token_limit` overrides it). **verified**
  [models-manager/models.json](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/models-manager/models.json),
  [config_toml.rs L339-L340](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/config/src/config_toml.rs#L339-L340).
- Each turn result carries `usage: ThreadTokenUsage{total, last, model_context_window}` with `input_tokens`,
  `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens` — enough for the graph
  to track context size and cache-hit ratio per round without an LLM. **verified**
  [v2/thread.rs L1931-L1975](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L1931-L1975),
  [api-reference.md L212](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/sdk/python/docs/api-reference.md#L212).
- Rough budget (**inferred**): a first build turn that reads 15–30 files and runs tests a few times lands around
  60–150k tokens of history; each fix round adds the round's prompt + reads + test outputs (often 20–60k). Two or three
  rounds can reach the compaction threshold on a big change.

**B.2.3 Compaction — what survives**
- Auto-compaction fires at `min(model_auto_compact_token_limit, 90% of context_window)` = **244,800** tokens for the
  272k models unless configured lower; manual: `thread.compact()`. **verified**
  [protocol/src/openai_models.rs L527-L538](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/protocol/src/openai_models.rs#L527-L538),
  [config_toml.rs L180-L185](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/config/src/config_toml.rs#L180-L185).
- With the OpenAI provider (our ChatGPT login) compaction is **remote ("v2")**: the server returns one opaque
  `Compaction` item; Codex keeps only **user messages** (plus hook prompts and, optionally, client-authored developer
  messages and small inter-agent messages) up to a **64,000-token** budget, newest first. Assistant messages, reasoning
  and **all tool calls/outputs are dropped**. **verified**
  [session/turn.rs L1471-L1507](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/session/turn.rs#L1471-L1507),
  [model-provider/src/provider.rs L714-L750](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/model-provider/src/provider.rs#L714-L750),
  [compact_remote_v2.rs L73-L74, L494-L583](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/compact_remote_v2.rs#L494-L583).
- The local fallback (non-OpenAI providers) keeps user messages up to **20,000** tokens plus an LLM-written summary from
  a prompt that asks for a "handoff summary for another LLM" (progress and decisions; constraints and preferences; next
  steps; critical data/references). `compact_prompt` / `experimental_compact_prompt_file` override that prompt, but the
  remote path never reads it. **verified** [compact.rs L63, L673-L765](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/compact.rs#L673-L765),
  [prompts/templates/compact/prompt.md](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/prompts/templates/compact/prompt.md),
  [config_toml.rs L275, L557](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/config/src/config_toml.rs#L275);
  "remote ignores `compact_prompt`" is **inferred** from the absence of any reference in `compact_remote_v2.rs`.
- Consequences (**inferred**): (1) after a compaction the "hot" builder is running on an opaque server-side summary we
  cannot inspect; (2) findings or CI logs sent as `ExternalMessage` (stored as function-call outputs) do **not**
  survive remote compaction — the trusted parts of each fix-round prompt (finding ids, titles, file:line, required
  disposition) must be in a **user message** built by our code from state; raw untrusted text (log excerpts, reviewer
  prose) may ride in an `ExternalMessage` because it is only needed for the current round; (3) every fix-round prompt should re-state the open-findings ledger from LangGraph state, so
  nothing depends on what compaction kept.

**B.2.4 Prompt caching across rounds**
- Codex keeps the prefix append-only: per-turn overrides (model, permissions, cwd) are appended as new
  developer/user messages, and tests assert the cached prefix and `prompt_cache_key` stay constant across turns.
  **verified** [core/tests/suite/prompt_caching.rs L746-L874](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/tests/suite/prompt_caching.rs#L746-L874).
  The cache key defaults to the session id; a code comment says ChatGPT derives cache affinity from the session-id
  header. **verified** [core/src/client.rs L581-L597](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/client.rs#L581-L597).
- Retention: for GPT-5.6 and later the API docs give a single cache TTL, `30m` (also the default); cache **writes**
  cost 1.25x uncached input and reads 0.1x (0.05x on GPT-6.1 Sol); minimum cacheable prefix 1,024 tokens. **verified**
  [OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching) (fetched 2026-10-13).
  Codex sends no retention option (GitHub code search finds `prompt_cache_retention`/`prompt_cache_options` only in a
  docs sample and in a test asserting the field is absent). On resume over websockets it may first send a
  `generate: false` pre-warm request carrying the full history, then continue with `previous_response_id`.
  **verified** [core/tests/suite/client_websockets.rs L609-L716](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/tests/suite/client_websockets.rs#L609-L716).
- Consequences (**inferred**; whether the ChatGPT backend uses the same 30-minute TTL is not documented):
  - A **local-gate (S4) fix** happens seconds after the build turn → prefix is warm → re-reading 150k tokens of history
    costs ~10% (5% on GPT-6.1 Sol) of fresh input.
  - A **CI fix (S6)** or **review fix (S7/S8)** typically resumes after a CI wait or review longer than 30 minutes →
    the first request of the round re-reads the whole history **uncached** (and pays a cache write), later requests
    in the round hit the cache again. Compaction also rewrites the prefix → one more cold request.
  - Worked example with the published GPT-6.1 Sol credit rates (50 input / 2.5 cached / 250 output per 1M):
    resuming a 200k-token thread costs ~10 credits for the first, cold request (more if the plan also charges the
    API's 1.25x cache-write premium — not documented) and ~0.5 credits for each later cached request; a fix round
    that emits 20k output+reasoning tokens costs ~5 credits. So after a long CI wait the cold re-read of a big
    thread can cost about twice the round's own output. And every model request inside the round (one per tool
    call) bills the whole prefix again, mostly at the cached rate: 30 requests × 0.5 = ~15 credits of cached re-reads
    on a 200k-token thread versus ~2–4 on a thread that starts from a 10k-token handoff. (**inferred** arithmetic on
    **verified** rates; per-request re-billing is the Responses API model, not separately verified for the ChatGPT
    backend.)
  - So "hot" context is cheap only while the wait is short. A 200k-token resumed thread after a 45-minute CI run costs
    more on its first request than a fresh builder that starts from a 5–10k-token handoff, although the fresh builder
    then re-reads files.

**B.2.5 Does cached input count less against the ChatGPT plan?**
- Codex credit rate card (Standard speed, credits per 1M tokens, input / cached input / output): GPT-6 Astra
  250 / 25 / 1,250; GPT-6.1 Sol 50 / 2.5 / 250; GPT-6 Sol 50 / 5 / 250; GPT-6 Luna 2.5 / 0.25 / 12.5; GPT-5.5
  125 / 12.5 / 750 — cached input is **10% of fresh input (5% on GPT-6.1 Sol)**; the page says model, context,
  reasoning, tool use, retrieval **and caching** all change how much allowance a task uses; Pro "currently" has no
  five-hour limit (weekly limits may apply). **verified** [learn.chatgpt.com/docs/pricing](https://learn.chatgpt.com/docs/pricing)
  (fetched 2026-10-13; the help-center "Codex rate card" article returned HTTP 403). The page does not say in words that
  the *included* allowance is debited with the same weights; cache writes are not listed on the rate card.
- The app-server can tell us directly: `account/usage/read {threadId}` returns `threadUsage{estimatedUsageCreditsMicros,
  groups[{model, reasoningEffort, speed, estimatedUsageCreditsMicros, netNewInputTokens, cachedInputTokens, inputTokens,
  outputTokens}]}` ("estimated usage when ... its billing route is available"), and `account/rateLimits/read` returns
  `primary`/`secondary` windows with `usedPercent`, `windowDurationMins`, `resetsAt`. Neither is wrapped by the Python
  SDK (raw JSON-RPC). **verified** [v2/account.rs L314-L345, L436-L456](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L436-L456),
  [v2/thread_usage.rs L9-L29](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/v2/thread_usage.rs#L9-L29),
  [common.rs L1328-L1344](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/app-server-protocol/src/protocol/common.rs#L1328-L1344).
  Recommendation (**inferred**): record `estimatedUsageCreditsMicros` per thread after each node, and the rate-limit
  `usedPercent` before/after each run, in LangGraph state — that settles "does caching count less" for our account
  with data instead of assumptions.

**B.2.6 Guardrails for one resumed builder thread (inferred, built on the facts above)**
1. Keep the builder thread across S4 → S3 retries and S6/S8 fix rounds (owner decision). Store `thread_id` in state.
2. Each fix-round prompt is generated by code: the open-findings ledger (ids, priority, file:line, title, required
   disposition) in the user message; raw CI-log excerpt / reviewer bodies either fenced as data in that same message
   (simplest for the prototype) or as an `ExternalMessage` joining the turn (cleaner authority separation).
3. Builder turn returns the same structured handoff every round (B.4) — this is what the PR body, the next reviewer
   and S10 use; never the thread transcript.
4. Watch `usage.total.input_tokens` / `model_context_window`: above ~60% of the window before a CI-wait round, or after
   a compaction has happened twice, start a **fresh builder thread seeded from the latest handoff + ledger** instead of
   resuming (a code rule, no LLM). Same for a "no progress" strike (same failure fingerprint twice).
5. Set `sandbox`, `approval_mode`, `effort` explicitly on every resumed turn (sticky overrides).

### B.3 Self-review vs independent review, and long-thread degradation — short evidence

Self-review (kept short per owner decision):
- Intrinsic self-correction without external feedback **lowers** accuracy (GPT-3.5 CommonSenseQA 75.8% → 38.1%; GPT-4
  GSM8K 95.5% → 89.0%) — Huang et al. ICLR 2024, **V** [arXiv](https://arxiv.org/html/2310.01798). Survey: no study
  shows reliable correction from a model's own prompted feedback; it works with reliable external feedback — Kamoi et
  al. TACL 2024, **V(abs)** [arXiv](https://arxiv.org/abs/2406.01297).
- Models find their own errors poorly but fix them well **once given the location** — Tyen et al. ACL Findings 2024,
  **V(abs)** [arXiv](https://arxiv.org/abs/2311.08516) → findings must carry file:line.
- Self-repair is bottlenecked by feedback quality; stronger-model or human feedback helps far more — Olausson et al.
  ICLR 2024, **V(abs)** [arXiv](https://arxiv.org/abs/2306.09896); execution feedback (unit tests) beats self-explanation
  (Self-Debugging up to +12% vs +2–3%) — **V(abs)** [arXiv](https://arxiv.org/abs/2304.05128).
- LLM judges recognise and favour their own outputs — Panickssery et al. NeurIPS 2024, **V** [NeurIPS](https://neurips.cc/virtual/2024/oral/97998);
  on a Python 2→3 migration, same-model self-review approved 31.7% of its own behaviour-changing edits — Reddy et al.
  2026, **V(abs)** [arXiv](https://arxiv.org/abs/2605.21537).
- Vendor guidance: Claude Code docs — a fresh context improves code review because the reviewer is not biased toward
  code it just wrote; a reviewer subagent sees only the diff and the criteria, not the reasoning; a reviewer asked to
  find gaps will usually report some even when the work is sound, so limit it to correctness and stated requirements —
  **V** [best practices](https://code.claude.com/docs/en/best-practices) (fetched 2026-10-13). Anthropic: tuning a
  separate, sceptical evaluator is far more tractable than making the builder self-critical — **V**
  [harness design, 2026-03-24](https://www.anthropic.com/engineering/harness-design-long-running-apps). Codex's own
  `/review` is fresh-context (B.1).

Degradation when **one builder thread** is resumed across fix rounds (relevant to the owner's resume decision):
- Multi-turn: spreading a task over several turns made results 39% worse on average across 15 models, mostly through
  unreliability (+112% variance) from early assumptions; consolidating everything into a fresh conversation is the
  recommended fix — Laban et al. 2025, **V** [arXiv](https://arxiv.org/html/2505.06120).
- Repeated repair: most code models lose 60–80% of debugging effectiveness within 2–3 attempts; a well-timed fresh
  start recovers it — Debugging Decay Index, Scientific Reports 2025, **V(abs)** [arXiv](https://arxiv.org/abs/2506.18403).
  Claude Code docs: after two failed corrections, clear and restart with a better prompt — **V** (same page as above).
- Long context: accuracy drops with input length even on easy tasks (Chroma "Context Rot", 18 models — **V**
  [report](https://www.trychroma.com/research/context-rot)); information in the middle is used worst (Liu et al. TACL
  2024 — **V** [arXiv](https://arxiv.org/html/2307.03172)).
- Reading (**I**): resuming is right for the first fix round (the builder knows its code, cache may be warm); by the
  second failed attempt at the same problem the evidence favours a fresh builder seeded with a consolidated handoff —
  which is what rule B.2.6-4 does.

### B.4 Handoff: what mature agent systems capture (templates)

Legend as elsewhere; **V-obs** = checked by reading real PRs/comments via the GitHub API (2026-10-13). Field and
section names are listed; prose is paraphrased.

**B.4.1 The five systems the owner named**

| System | PR body (sections; who writes what) | Fix-round input / memory | Evidence |
|---|---|---|---|
| **GitHub Copilot coding agent** ("Copilot cloud agent") | During the run a `report_progress(commitMessage, prDescription)` tool commits, pushes and rewrites the PR body as `## Plan` + `- [x]/- [ ]` checklist. After the loop, a follow-up prompt **in the same session** (the guide notes the LLM still has full context) asks for `<pr_title>` / `<pr_description>`, which replaces the checklist. Follows the repo `pull_request_template.md` (picks the best fit if several). Notes resources it could not access. Commit messages link to the session log; the requesting human is co-author. | Review comments arrive as a `fix-pr-comment` job whose problem statement restates the PR context and the comments; `reply_to_comment(commentId, message)` answers each thread. Copilot keeps context from earlier sessions on the same PR. | **V** [copilot-engine-sdk integration-guide L350-L457, L582-L620 @6742121](https://github.com/github/copilot-engine-sdk/blob/6742121a6bddc07acdfd6b789ddd00f9acce7138/docs/integration-guide.md#L350-L457); [changelog 2025-11-05](https://github.blog/changelog/2025-11-05-copilot-coding-agent-now-supports-pull-request-templates/); [responsible use](https://docs.github.com/en/copilot/responsible-use/agents); [cloud-agent docs](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github) |
| **Devin** | Looks for `DEVIN_PR_TEMPLATE.md` (several locations) before GitHub's template names. Default without template: one `## Summary` written for a reader who has not seen the diff; observed bodies (May 2026) also had `## Review & Testing Checklist for Human` (checkboxes) and `### Notes`. Footer added outside the model text: session link, requester, Devin Review badge. | Same live session answers PR comments; bot comments ignored by default except lint/CI failures. Devin Review groups findings as Bugs (severe / non-severe), Flags (investigate / informational), Security (critical / warning); bugs and security are posted by default, flags are not. | **V** [PR templates](https://docs.devin.ai/integrations/pr-templates), [Devin Review](https://docs.devin.ai/work-with-devin/devin-review), [bot comments](https://docs.devin.ai/product-guides/bot-comment-settings); **V-obs** [whatsapp-rust#10](https://github.com/fifteenlabs/whatsapp-rust/pull/10), [litellm#42813](https://github.com/BerriAI/litellm/pull/42813) |
| **LangChain Open SWE** | Current: follow repo conventions (AGENTS.md, templates); `open_pull_request` opens a **draft**, code appends `## References` and a footer naming thread + model. May-2026 v2 tool: title `<type>: <desc> [closes PROJ-N]`, body `## Description` (why + approach, no file lists), `## Release Note`, `## Test Plan` (checkboxes, new verification only), `Co-authored-by` for the requester. v1: `Fixes #N` + owner + a body built from completed plan items and per-task summaries. Never amend/rebase pushed commits (reviewers rely on inter-commit diffs). | Fix runs are scoped to `conflicts`, `checks` or review comments; the agent replies on each thread (fixed / why not) but does not resolve; gets a PR status snapshot marked possibly stale. Reviewer findings and `update_finding{status open\|resolved\|dismissed, note}` live in thread metadata (see A). | **V** [commit-pr.md @0942b41](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/resources/prompts/system/commit-pr.md), [open_pull_request.md](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/resources/prompts/tools/open_pull_request.md), [commit_and_open_pr.py L84-L113 @13f5d8a](https://github.com/langchain-ai/open-swe/blob/13f5d8a1c9997f564cb2b0517e15933095233b07/agent/tools/commit_and_open_pr.py#L84-L113), [v1 open-pr.ts L52-L67 @c173ff2](https://github.com/langchain-ai/open-swe/blob/c173ff28dda205ff3ece36239d80f75c6f36309d/apps/open-swe/src/graphs/programmer/nodes/open-pr.ts#L52-L67), [pull-request-fix-scope.md.jinja](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/resources/prompts/runs/pull-request-fix-scope.md.jinja) |
| **OpenHands resolver** (V0, removed 2026-04-23; read at last commit) | Output record `ResolverOutput{issue, issue_type, instruction, base_commit, git_patch, history, metrics, success, comment_success, result_explanation, error}`. `success` + explanation come from a **separate** model call that sees issue, patch and the agent's last message. PR: branch `openhands-fix-issue-N`, title `Fix issue #N: <title>`, body = closing line + `result_explanation` + signature; draft by default; no PR unless `success` (or `--send-on-failure`). | On an existing PR: push to the head branch, one summary comment with a bullet per explanation, and a reply on **each unresolved thread** with that thread's explanation. | **V** [resolver_output.py L15-L27 @e7934ea](https://github.com/OpenHands/OpenHands/blob/e7934ea6e57c9097d85bcc07ac7827e301225acd/openhands/resolver/resolver_output.py#L15-L27), [send_pull_request.py](https://github.com/OpenHands/OpenHands/blob/e7934ea6e57c9097d85bcc07ac7827e301225acd/openhands/resolver/send_pull_request.py), [issue-success-check.jinja](https://github.com/OpenHands/OpenHands/blob/e7934ea6e57c9097d85bcc07ac7827e301225acd/openhands/resolver/prompts/guess_success/issue-success-check.jinja) |
| **OpenAI Codex cloud** | "Create PR" body: `## Summary` (bullets), `## Testing` (each command prefixed ✅ or ⚠️, e.g. not run), rule, task URL. Skipped the repo template and `Fixes #` (issue #6750, closed). Task view cites terminal/test logs as evidence. Commit trailer `Co-authored-by: Codex <noreply@openai.com>`. | `@codex <task>` on a PR starts a cloud task with the PR as context; `@codex review` posts a normal GitHub review flagging only P0/P1 and following AGENTS.md review rules. | **V-obs** [kryptonit-stack#17](https://github.com/gitPHhuber/kryptonit-stack/pull/17), [permitassistpro#4](https://github.com/workstying-cloud/permitassistpro/pull/4); **V** [openai/codex#6750](https://github.com/openai/codex/issues/6750), [GitHub integration docs](https://learn.chatgpt.com/docs/third-party/github), [git-attribution world_state.rs L9-L20](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/ext/git-attribution/src/world_state.rs#L9-L20); log citations only via search-indexed text of "Introducing Codex" (direct fetch 403) |

**B.4.2 Other agents (one line each; all V unless marked)**
- Claude Code GitHub Action v1.0.248: one tracking comment edited in place (todo checklist, header with duration,
  links, final summary of what was and was **not** done); offers a prefilled compare link instead of opening the PR.
  [create-prompt L595-L607, L725-L810](https://github.com/anthropics/claude-code-action/blob/1d6de8cb0c237e7c15e9e1bdf973826ebae490cc/src/create-prompt/index.ts#L595-L607).
- Cursor cloud agents: agent text between `<!-- CURSOR_AGENT_PR_BODY_BEGIN/END -->` markers; Bugbot owns a separate
  `<!-- CURSOR_SUMMARY -->` block with a risk level and "reviewed for commit `<sha>`" (**V-obs**
  [PrintPartner#225](https://github.com/poitee/PrintPartner/pull/225)).
- Factory `@droid fill`: fills the repo template, else overview / changes / testing / rollout
  ([droid-action README L227-L231](https://github.com/Factory-AI/droid-action/blob/736445d3fe7133d7e47c54ee1ecb86ad82bae289/README.md#L227-L231)).
- Google Jules: free text + code-added footer with task link and requester; a "critic" reviews before submission
  ([critic post](https://developers.googleblog.com/en/meet-jules-sharpest-critic-and-most-valuable-ally/)).
- GitLab Duo Developer Flow: draft MR linked to the issue, plan then implementation; MR body fields not documented
  ([docs](https://docs.gitlab.com/user/project/merge_requests/developer/)). Aider: one-line Conventional Commit from
  diff + chat ([prompts.py L7-L22](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/prompts.py#L7-L22)).

**B.4.3 Structured handoff notes between sessions**

| System | Fields | Evidence |
|---|---|---|
| Anthropic "Effective harnesses for long-running agents" (2025-11-26) | `claude-progress.txt` log; `feature_list.json` `{category, description, steps, passes}`; `init.sh`; descriptive commits; each session starts by reading git log + progress file; must not edit tests; end in a clean state | **V** [post](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) |
| OpenAI ExecPlans (`PLANS.md`) | Living sections: Progress (timestamped checkboxes), Surprises & Discoveries (observation + evidence), Decision Log (decision / rationale / date-author), Outcomes & Retrospective; plus Purpose, Context, Plan of Work, Validation and Acceptance, Idempotence and Recovery, Interfaces | **V** [codex_exec_plans.md L84-L165 @857eb0b](https://github.com/openai/openai-cookbook/blob/857eb0b0a3419b7868ea768f1de3ee906cf176e4/articles/codex_exec_plans.md#L84-L165) |
| Sourcegraph Amp `/handoff` (2025-10-23) | Instead of compaction: draft a new-thread prompt + list of relevant files for a stated goal, editable before sending; Amp calls stacked summaries lossy | **V** [post](https://ampcode.com/news/handoff) |
| Codex compaction prompt | progress + decisions; constraints/preferences; next steps; critical data/references (B.2.3) | **V** (B.2.3) |
| LangChain SummarizationMiddleware | `## SESSION INTENT`, `## SUMMARY` (decisions, reasons, rejected options), `## ARTIFACTS` (paths + what changed), `## NEXT STEPS`; empty = "None" | **V** [summarization.py L57-L95 @f2bf626](https://github.com/langchain-ai/langchain/blob/f2bf626ccee0a0e88d560706d4fdad35e43116e5/libs/langchain_v1/langchain/agents/middleware/summarization.py#L57-L95) |
| Cline Memory Bank; Manus `todo.md` | projectbrief / activeContext / progress files read at every task start; Manus rewrites `todo.md` to keep goals near the end of context and keeps errors in context | **V** [Cline](https://docs.cline.bot/best-practices/memory-bank), [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) |
| Anthropic multi-agent research system | lead saves plan to memory; subagents write to external storage and return lightweight references; each brief has objective, output format, tool guidance, boundaries | **V** [post](https://www.anthropic.com/engineering/multi-agent-research-system) |

**B.4.4 Commit trailers / git metadata**
- Linux kernel (v7.3-rc7): `Assisted-by: LLM [TOOL…]`, AI must not add `Signed-off-by`; bug-fix procedure asks to state
  what could not be done. [coding-assistants.rst](https://github.com/torvalds/linux/blob/v7.3-rc7/Documentation/process/coding-assistants.rst).
  Fedora: `Assisted-by: <assistant>` ([proposal](https://communityblog.fedoraproject.org/council-policy-proposal-policy-on-ai-assisted-contributions/)).
- `Co-authored-by` by default: Codex (`Codex <noreply@openai.com>`), Claude Code, Copilot (human as co-author), Open SWE.
- Machine-readable attribution: git-ai standard v3 keeps authorship logs in `refs/notes/ai`
  ([spec L13-L52](https://github.com/git-ai-project/git-ai/blob/0670e7ef27590af0e8ff5409267f3f4b09b8fcb4/specs/git_ai_standard_v3.0.0.md#L13-L52));
  Agent Trace v0.1.0 RFC defines a JSON trace record ([agent-trace.dev](https://agent-trace.dev/)).

**B.4.5 Finding threads and dispositions**

| System | How a finding is closed | Evidence |
|---|---|---|
| GitHub GraphQL | `resolveReviewThread(threadId, resolutionReason)`; `resolutionReason ∈ {ADDRESSED, WONT_FIX, INVALID}`; thread has `isResolved`, `isOutdated`, `path`, `line` | **V** live introspection 2026-10-13 (re-checked by me) |
| Copilot code review | Resolve reasons Addressed / Won't fix / Incorrect (2026-08-27); resolves its own comments after fixing commits, overview groups Open / Resolved since last review / Previously missed (2026-09-18) | **V** [08-27](https://github.blog/changelog/2026-08-27-copilot-code-review-resolution-reasons-and-expanded-capabilities/), [09-18](https://github.blog/changelog/2026-09-18-copilot-code-review-an-improved-review-experience/) |
| CodeRabbit | Comment header category / severity / effort, hidden fingerprint markers, appends "Addressed in commit `<sha>`"; `@coderabbitai review` = new changes only, `full review` = everything | **V** [commands](https://docs.coderabbit.ai/reference/review-commands); **V-obs** [anubis-mcp#314](https://github.com/zoedsoupe/anubis-mcp/pull/314) |
| Claude Code Review | 🔴 Important / 🟡 Nit / 🟣 Pre-existing; check run with severity table + machine-readable counts; reruns on push resolve fixed threads | **V** [docs](https://code.claude.com/docs/en/code-review) |
| PR-Agent | `persistent_comment`, `persistent_finding_state`, `max_previous_findings_chars = 8000` (earlier findings fed back so wording is kept and human-resolved threads are skipped), `num_max_findings = 3`, optional `require_merge_recommendation` (`no_concerns_found \| needs_review \| changes_required`) | **V** [configuration.toml L168-L199 @330f081](https://github.com/The-PR-Agent/pr-agent/blob/330f0813b5fe0d1f54b794077c2d02aa85a1fb63/pr_agent/settings/configuration.toml#L168-L199) (re-checked by me) |
| Gerrit | each comment resolved/unresolved; quick replies **Done** (fixed next patch set) and **Ack** (no change) | **V** [docs](https://gerrit-review.googlesource.com/Documentation/user-review-ui.html) |

**B.4.6 Patterns across systems** (**inferred** synthesis of the rows above)
1. Two-phase PR body: live checklist while working, replaced by a final summary written while the builder still has
   context (Copilot, Claude Code Action).
2. Each writer owns a region: model text between markers, code-owned footer (links, attribution, closing keyword),
   other bots in their own blocks (Cursor, Bugbot, Copilot suffixes, Open SWE references).
3. Links, closing keywords and attribution are added by code, not by the model (OpenHands, Devin, Jules, Codex, Open SWE).
4. Evidence is pinned to a SHA ("reviewed for commit", "addressed in commit", `last_reviewed_sha`).
5. Dispositions converge on three states: fixed / won't fix / invalid (GraphQL enum, Open SWE resolved/dismissed,
   Gerrit Done/Ack).
6. GitHub caps PR bodies at 65,536 characters ([community #27190](https://github.com/orgs/community/discussions/27190)) — keep the body bounded.


---

## C. CI "fix or move on" without an LLM

Sibling `03` §5 already covers the GitHub reads (check runs, jobs, statuses, rollup), the
`pending | success | failure | blocked | missing | conflict | head_moved | timeout` classifier, log download and the
rerun endpoint. This section adds failure **classes** and **policy**. Legend: **V** verified (permalink or docs
fetched 2026-10-13; "live" = read-only GitHub REST call on a public repo); **I** inferred. I re-checked the two
load-bearing items myself (timeout → `cancelled`; Chromium "without patch").

### C.1 Where the signal lives on GitHub Actions (cheapest first) — and two corrections to the `03` classifier

1. **Workflow run** `conclusion`: `startup_failure` (invalid workflow) and `action_required` (awaiting approval) runs
   can have **zero jobs and no check runs**, so a check-run-only classifier reports them as `missing`. **V** live
   ([microsoft/vscode run 38305963743](https://github.com/microsoft/vscode/actions/runs/38305963743)); `startup_failure`
   is a check-suite-level state ([status checks](https://docs.github.com/en/pull-requests/reference/status-checks)).
2. **Job** (`conclusion ∈ success|failure|neutral|cancelled|skipped|timed_out|action_required`, `runner_name`,
   `run_attempt`, `steps[{name, conclusion}]`) — the failing **step name** is available without logs. **V**
   [workflow-jobs REST](https://docs.github.com/en/rest/actions/workflow-jobs).
3. **Check-run annotations** — runner errors appear as `failure` annotations (max 10 errors + 10 warnings per step).
   **V** [checks REST](https://docs.github.com/en/rest/checks/runs).

**A job-level timeout ends `cancelled`, not `timed_out`**; only the annotation "The job has exceeded the maximum
execution time of 15m0s" (plus "The operation was canceled.") tells it apart from a concurrency cancel. **V** live, re-checked
([wangzitian0/finance_report job 115103957380](https://github.com/wangzitian0/finance_report/actions/runs/38338349904/job/115103957380)).
So `03` §5.2's rule "required check `cancelled` on the current SHA → `blocked`" must first read annotations.

### C.2 Deterministic signatures (GitHub Actions; runner v2.338.0 source)

| Class | Match on | Job conclusion | Evidence |
|---|---|---|---|
| Job timeout | annotation `exceeded the maximum execution time of` | `cancelled` | **V** live (C.1) |
| Step timeout | `The action '<step>' has timed out after <n> minutes.` | `failure` | **V** [StepsRunner.cs L322-L337](https://github.com/actions/runner/blob/197ca027b90de199464dee3bb9ff198a1db60967/src/Runner.Worker/StepsRunner.cs#L322-L337) |
| Superseded (concurrency) | `Canceling since a higher priority waiting request for <group> exists` | `cancelled` | **V** live |
| Runner not acquired | `The job was not acquired by Runner of type hosted even after multiple attempts`; `runner_name == ""`, `steps == []` | `cancelled` | **V** live ([giantswarm job 111948676007](https://github.com/giantswarm/mcp-template/actions/runs/37365239036/job/111948676007)) |
| Runner lost | `The hosted runner: <name> lost communication with the server` (maintainers: often the workflow starving CPU/RAM/IO) | failure | **V** [runner-images#9823](https://github.com/actions/runner-images/issues/9823) |
| Runner shutdown | `The runner has received a shutdown signal.` / `Operating system is shutting down` | — | **V** [JobRunner.cs L133-L136](https://github.com/actions/runner/blob/197ca027b90de199464dee3bb9ff198a1db60967/src/Runner.Worker/JobRunner.cs#L133-L136) |
| Step exit | `Process completed with exit code <n>.` | failure | **V** [ScriptHandler.cs L352-L356](https://github.com/actions/runner/blob/197ca027b90de199464dee3bb9ff198a1db60967/src/Runner.Worker/Handlers/ScriptHandler.cs#L352-L356) |
| Disk | warning `You are running out of disk space…`; `No space left on device`; `ENOSPC` | failure | **V** [JobExtension.cs L1199-L1203](https://github.com/actions/runner/blob/197ca027b90de199464dee3bb9ff198a1db60967/src/Runner.Worker/JobExtension.cs#L1199-L1203) |
| Action / image fetch | `Failed to download action '<url>'` (runner already retried 3×), `Docker pull failed with exit code <n>` (3 attempts), `Access denied to '<url>'` | failure in "Set up job" | **V** [ActionManager.cs L937-L963](https://github.com/actions/runner/blob/197ca027b90de199464dee3bb9ff198a1db60967/src/Runner.Worker/ActionManager.cs#L937-L963) |
| Network (any tool) | Argo's transient list: `connection reset by peer`, `i/o timeout`, `TLS handshake timeout`, `connection refused`, `http2: … GOAWAY`; npm `ECONNRESET\|ENOTFOUND\|ETIMEDOUT\|EAI_FAIL` | failure | **V** [argo errors.go L120-L151 @v4.1.5](https://github.com/argoproj/argo-workflows/blob/v4.1.5/util/errors/errors.go#L120-L151), [npm error-message.js @v12.2.0](https://github.com/npm/cli/blob/v12.2.0/lib/utils/error-message.js#L274-L285) |
| Rate limit | HTTP 429 / `You have reached your pull rate limit` (Docker Hub: 100 pulls / 6 h anonymous); GitHub 403/429 with `x-ratelimit-remaining: 0` or `secondary rate` | failure | **V** [Docker](https://docs.docker.com/docker-hub/usage/pulls/), [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) |
| Memory | exit 137 (128 + SIGKILL) in a **failure** job; `JavaScript heap out of memory`; `MemoryError`; `OutOfMemoryError` | failure | **V** [bash exit status](https://www.gnu.org/software/bash/manual/html_node/Exit-Status.html), [node_errors.cc @v26.11.1](https://github.com/nodejs/node/blob/v26.11.1/src/node_errors.cc#L620-L627) |

Notes: on cancel the runner sends SIGINT → SIGTERM → kill, so 130/143/137 inside a `cancelled` job are effects, not
causes (**V** [cancellation docs](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation); reading **I**).
OOM policy differs: GitLab's example retries exit 137, Jenkins deliberately does **not** retry `OOMKilled` (author's
problem) — **V** [Jenkins KubernetesAgentErrorCondition.java L59-L60](https://github.com/jenkinsci/kubernetes-plugin/blob/c25b83890c3435e2a1a019b6ff00b2af56ea3e21/src/main/java/org/csanchez/jenkins/plugins/kubernetes/pipeline/KubernetesAgentErrorCondition.java#L59-L60).
Match network regexes only in setup/install steps or on the last error line — tests that exercise network errors would
otherwise look like infra (**I**).

**Built-in failure-reason taxonomies elsewhere** (all **V**): GitLab `retry:when` — `script_failure`, `api_failure`,
`runner_system_failure`, `scheduler_failure`, `data_integrity_failure`, `unknown_failure`, … (19.1 added
`runner_configuration_error`, `runner_external_dependency_failure`, `runner_interrupted`), `max` 0–2, plus
`retry:exit_codes` ([doc @87e7591](https://gitlab.com/gitlab-org/gitlab/-/blob/87e7591392e5db49c9dfaa63890f54ade34077d4/doc/ci/yaml/_index.md));
Buildkite `retry.automatic` by `exit_status` (−1 = agent lost) and `signal_reason` (`agent_stop`, `cancel`, …), limit ≤ 10
([docs](https://buildkite.com/docs/pipelines/configure/retry)); CircleCI auto-retries `infrastructure_fail` at most 2×
and only before user steps ([support 2026-05-14](https://support.circleci.com/hc/en-us/articles/44168007038235-CircleCI-Infrastructure-Failures-Detection-and-Handling));
Jenkins `retry(conditions: [agent()])` never retries user aborts ([steps](https://www.jenkins.io/doc/pipeline/steps/workflow-basic-steps/)).
Common shape: **infra classes auto-retry a little; script failures go back to the author.**

### C.3 Flaky tests

- **Definition used by every vendor: the same code fails and then passes** — same commit SHA (Datadog, CircleCI
  Insights 14-day window, Mergify "same job, same pipeline, same SHA", Trunk pass-on-retry), same git tree SHA
  (BuildPulse) or same input hash (Nx Cloud, retried once on a different agent). **V**
  [Datadog](https://docs.datadoghq.com/tests/flaky_tests/), [CircleCI](https://circleci.com/docs/guides/insights/insights-tests/),
  [Mergify](https://docs.mergify.com/ci-insights/), [Trunk @73e52a3](https://github.com/trunk-io/docs/tree/73e52a392ac970593bad9f51a7206e3e217bc097/flaky-tests/detection),
  [BuildPulse](https://docs.buildpulse.io/flaky-tests/overview), [Nx](https://canary.nx.dev/docs/features/ci-features/flaky-tasks).
- History-based monitors: Trunk failure-rate 30% over 6 h / ≥ 50 runs; Buildkite transition-count and probabilistic
  monitors; Meta's Bayesian probabilistic flakiness score ([2020](https://engineering.fb.com/2020/12/10/developer-tools/probabilistic-flakiness/)). **V**
- **Guard: mass failure is not flakiness** — Trunk excludes uploads where > 80% of tests fail; Gradle test-retry's
  `maxFailures` stops retrying when many tests fail; Chromium aborts retries when ≥ 5 suites fail ("most likely
  indicates a problem with the CL"). **V** (Trunk above; [Gradle README @v1.6.6](https://github.com/gradle/test-retry-gradle-plugin/blob/v1.6.6/README.adoc#L15-L32);
  Chromium below).
- Scale: Google ~1.5% of test runs flaky, ~16% of tests have some flakiness, ~84% of pass→fail transitions involve a
  flaky test; flaky-marked tests report failure only after 3 consecutive failures. **V** [Google Testing Blog 2016](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html).
- Runner-level signals we can read for free: Bazel `FLAKY`, pytest-rerunfailures `--fail-on-flaky` (exit 7),
  Playwright outcome `flaky`, Surefire `<flakyFailure>`. **V** ([pytest-rerunfailures 16.7](https://github.com/pytest-dev/pytest-rerunfailures/blob/16.7/docs/cli.rst), [Playwright](https://playwright.dev/docs/test-retries), [Surefire](https://maven.apache.org/surefire/maven-surefire-plugin/examples/rerun-failing-tests.html)).

### C.4 Pre-existing failures and failures unrelated to the change

- **Chromium CQ** runs failing suites three ways — with patch, retry with patch, **without patch** — and ignores
  failures that also fail without the patch (reported as "Tests failed with patch, but ignored as they also fail without
  patch"); known flakes are exonerated via LUCI Analysis; retries abort at ≥ 5 failing suites; the without-patch step is
  skipped when the CL touches the test specs. **V** [test_utils/api.py @44df25f](https://chromium.googlesource.com/chromium/tools/build/+/44df25fe3ba7f2c5030de60aa7befd4b56847831/recipes/recipe_modules/test_utils/api.py)
  (re-checked: L63-L65, L522-L530, L907), [chromium_tests/api.py](https://chromium.googlesource.com/chromium/tools/build/+/44df25fe3ba7f2c5030de60aa7befd4b56847831/recipes/recipe_modules/chromium_tests/api.py).
- **LUCI exoneration**: ≤ 20 runs around the commit within 14 days; suggested thresholds 6 unexpected in any 10-run
  window, or 3 consecutive. **V** [test_variants.proto L287-L350](https://github.com/luci/luci-go/blob/2d342008ddf5c1db8565c30e22a3da7169976f54/analysis/proto/v1/test_variants.proto#L287-L350).
- **Mozilla Treeherder** classifications (fixed by commit, expected fail, intermittent, infra, new failure, …); a failed
  job is auto-marked intermittent when its failing groups pass ≥ 50% of the time across retriggers and recent pushes.
  **V** [intermittents.py L107-L273](https://github.com/mozilla/treeherder/blob/962aceef5f3922b1e01f0024e24f556ba2a5886b/treeherder/log_parser/intermittents.py#L107-L273).
- **OpenShift Prow retester**: `/retest-required` only for failing required jobs; `max_retests_for_sha_and_base: 1`,
  `max_retests_for_sha: 3`; then pause until the base changes; when the budget is spent, `/hold`. **V**
  [fileBackOffCache.go L104-L136](https://github.com/openshift/ci-tools-standalone/blob/f74d64f4ac37cfc8fa5308ff5a689a14f668c37e/internal/retester/fileBackOffCache.go#L104-L136),
  [_config.yaml](https://github.com/openshift/release/blob/265a0d57adb480d9ef5ddc365e3d87a4ca52e205/core-services/retester/_config.yaml).
- **Is base red for the same job?** (tested live on this repo, 2 calls): latest completed `push` run of the same
  workflow on the base branch → its jobs → compare job **and failing step / test ids**, not just colour; or
  `GET /commits/{base_sha}/check-runs?check_name=<job>&filter=latest`. Gotchas: PR runs test the merge commit; a rerun
  reuses the same `GITHUB_SHA` (a fix on base needs a new push or update-branch); PR-only workflows have no base
  baseline → treat as unknown, no exoneration. **V** [events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [re-runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs) / **I** (policy).
- Relevance to the diff: Bazel `rdeps` + `tests()`; Meta predictive test selection caught > 99.9% of regressions
  running a third of dependent tests ([2018](https://engineering.fb.com/2018/11/21/developer-tools/predictive-test-selection/)). **V**
  For our size of repo, "failing step/test also fails on base" is the cheap, sufficient relevance test (**I**).

### C.5 What existing bots do (trigger → classification → action → caps)

| Bot | Classification | Action | Caps | Evidence |
|---|---|---|---|---|
| Open SWE `/baby-sit` | deterministic aggregation; but **flaky vs real is decided by the LLM** | flaky → `gh run rerun --failed`; deterministic → report or fix; ambiguous → stop | 3 reruns per head (reset on new head); dedupe `sha256(head\|retry)` | **V** [baby_sit.py @0942b41](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/baby_sit.py#L454-L534), [SKILL.md](https://github.com/langchain-ai/open-swe/blob/0942b41561df7db968f3be7f1c5150819bdec6b8/openswe/bundled_skills/baby-sit/SKILL.md) |
| Mergify auto-retry | rules on job name, conclusion, flaky flag, and a per-line **`log_pattern` regex** (2026-03-23) | rerun failed jobs or whole workflow | 1–10 retries | **V** [docs](https://docs.mergify.com/ci-insights/auto-retry/), [changelog](https://docs.mergify.com/changelog/2026-03-23-log-pattern-matching-for-auto-retry-rules/) |
| Renovate | branch status only | never automerges on red; raises a PR if tests fail or stay pending 25 h | no reruns | **V** [options @44.155.2](https://github.com/renovatebot/renovate/blob/44.155.2/docs/usage/configuration-options.md?plain=1#L322-L342) |
| Dependabot | none | relies on required checks for auto-merge | — | **V** [docs](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/automating-dependabot-with-github-actions) |
| Copilot cloud agent | none documented | human-triggered "Fix with Copilot" on failing Actions | none documented | **V** [changelog 2026-05-18](https://github.blog/changelog/2026-05-18-one-click-fixes-for-failing-actions-with-copilot-cloud-agent/) / **I** |
| Codex autofix (cookbook) | none | on `workflow_run` failure: minimal fix → tests → PR | none (loop risk) | **V** [Autofix-github-actions.ipynb @5bd6cb4](https://github.com/openai/openai-cookbook/blob/5bd6cb40b6b84b69b2032d810610aa85064102df/examples/codex/Autofix-github-actions.ipynb) |
| claude-code-action examples | none, or LLM `is_flaky` with confidence ≥ 0.7 → retry | fix branch or re-dispatch | branch-prefix loop guard only | **V** [ci-failure-auto-fix.yml @1d6de8c](https://github.com/anthropics/claude-code-action/blob/1d6de8cb0c237e7c15e9e1bdf973826ebae490cc/examples/ci-failure-auto-fix.yml#L19-L37) |
| GitLab Duo "Fix CI/CD pipeline" | LLM over the last 150 KiB of the job log | suggestions or MR; comment only if security-sensitive | — | **V** [docs](https://docs.gitlab.com/ci/pipelines/fix_pipeline/) |
| Nx Cloud self-healing CI | input-hash flakiness; AI for the rest | flaky → retry on another agent; auto-apply only for format/sync/conformance checks | 2 tries per flaky task | **V** [docs](https://nx.dev/docs/features/ci-features/self-healing-ci) |

Pattern (**I**): CI **platforms** classify deterministically (exit status, failure reason, log regex, same-SHA
history); coding **agents** either let the LLM decide or do not classify at all. S6 should take the platforms'
classification and the agents' loop guards and dedupe keys.

---

## D. Recommendations

Everything in D is **inferred** design, built on the verified facts in A–C (cross-references in brackets).

### D.1 Review-tier rubric — a pure-code node `S7a_pick_tier` before S7

**Inputs** (no LLM; computed from `git diff --numstat -z` / `--name-status` over `merge-base..head`, `.gitattributes`,
labels and graph state):

| Signal | Definition | Why (evidence) |
|---|---|---|
| `changed_lines` | additions + deletions, excluding `linguist-generated`, lockfiles, vendored and snapshot files | size predicts findings and defects [A.3: Prow, Google, SmartBear, Claude 31% vs 84%] |
| `files_changed` | count of non-excluded files | diffusion [A.3: Meta, Kamei] |
| `risk_classes` | glob table per repo (below) | location beats size for escalation [A.1 Chromium, k8s, RADAR blocklists] |
| `deps_changed` | manifest/lockfile dependency lines; `new_dependency` if a package name is new | deterministic gate exists [A.3 dependency-review] |
| `src_without_tests` | source globs changed, no test globs changed | lens choice |
| `label_override` | `review:none\|light\|standard\|deep` set by a **human** on issue or PR | override [A.3 labels] |
| `history` | blocking findings last round; CI-fix rounds; disputes | caps and escalation [A.6] |
| `builder_risk_flags` | areas the builder lists as risky in its handoff | may raise the tier, never lower it |

**Risk-class globs — example for this repo** (config, not code):

| Class | Globs |
|---|---|
| `ci_supply_chain` | `.github/workflows/**`, `.github/actions/**`, `images/**`, `**/Dockerfile*`, `compose*.yaml`, `versions.lock.json`, `pyproject.toml`, `**/requirements*.txt`, `**/*.lock` |
| `secrets_auth` | `ops/backup*`, `ops/bootstrap*`, `ops/activation*`, any path matching `*token*`, `*secret*`, `*credential*`, `*auth*`, `*passphrase*` |
| `agent_prompts` | `agents/**`, `AGENTS.md`, `CLAUDE.md`, `.agents/skills/**`, `**/SOUL.md` |
| `deploy_ops` | `ops/**`, `Makefile`, `config/**` |
| `schema_data` | `schemas/**`, `**/migrations/**` |
| `docs_only` / `tests_only` | `docs/**`, `**/*.md` (minus `agent_prompts`) / `tests/**` |

**Tier table** (first matching row from the top; a human label wins; nothing an agent writes can lower a tier):

| Tier | Selected when | Reviewers × lens | Model / effort | Blocks on | Review-fix cap | Re-review scope |
|---|---|---|---|---|---|---|
| **T3 deep** | any of `ci_supply_chain`, `secrets_auth`, `agent_prompts`, `schema_data`; `new_dependency`; `changed_lines` ≥ 500; label `deep` | 3 in parallel, distinct lenses: (1) correctness + acceptance criteria, (2) security / supply chain / ops — fed the output of `zizmor` / `gitleaks` / `hadolint` / `dependency-review` first (the candidate seat for a second model family, E.5), (3) tests + failure handling | strongest model; `high` (lens 1 `xhigh`) | P0/P1 from any lens, plus P2 with `category=security` | 2, then S10 | interdiff + open findings, by the lens(es) that raised them; one final full-diff pass by lens 1 only if the fixes changed > 30% of the originally reviewed lines |
| **T2 standard** | `changed_lines` 100–499, or `files_changed` ≥ 8, or `deploy_ops`, or `src_without_tests`, or dependency upgrade only | 1 generalist; + 1 conditional lens (tests if `src_without_tests`, ops if `deploy_ops`) | default model; `high` | P0/P1 | 2, then S10 | interdiff + open findings |
| **T1 light** | anything else with code (< 100 lines, < 8 files, no risk class) | 1 generalist | default model (or a cheaper one, cf. PR-Agent `model_routing`); `medium` | P0/P1 with `confidence ≥ 0.7` | 1, then S10 | interdiff only |
| **T0 none** | only `docs_only` / `tests_only` / generated files, CI green, no `agent_prompts` | 0 — deterministic checks only | — | — | — | — |

- Thresholds start from published anchors (Prow L = 100, XL = 500; Google ~100 fine / 1,000 too large; SmartBear
  ≤ 400) and should be re-fit on our own history after ~30 PRs (findings per tier, rounds, escaped defects).
- Size guard: `changed_lines` ≥ 1,000 → T3 and a note asking for a split (Google, SmartBear).
- Agent-authored PRs deserve the stricter bar (GitHub's extra-approval default; RADAR is stricter for AI codemods)
  — hence no "auto-approve" tier: S9 always ends at a human.
- A fix delta that touches a new risk class re-runs `pick_tier` (can only raise).
- Why 1 / 1–2 / 3 reviewers and distinct lenses rather than duplicates: see A.4.

**Fix-or-move-on after review (router code, no LLM):**
1. A finding is **blocking** iff `priority ≤ 1` (P0/P1) **and** `code_location` overlaps the reviewed range **and**
   `confidence_score ≥` the tier bar (T3 security lens: also P2 with `category=security`).
   - **Verify step (T2/T3 only):** each blocking finding first goes through a fresh read-only Codex turn at low
     effort that sees only the finding, the diff hunk and the files it names, and returns `{valid,
     introduced_by_change, reason}`; only `valid && introduced_by_change` findings reach the builder. Precedents: the
     Claude Code plugin validates every finding with its own subagent; Meta RADAR adds deterministic validation after
     the LLM review; RovoDev's actionability filter and BitsAI-CR's review filter were the biggest precision gains
     (A.1–A.2). Rationale (**inferred**): one small read-only call per blocking finding (usually 0–3) is cheaper than
     a builder round + CI + re-review spent on a false positive, and a builder tends to "fix" whatever it is told is
     wrong.
2. Everything else — P2/P3, low confidence, outside the diff, pre-existing — is **non-blocking**: fingerprinted, rendered
   once in the PR body under "Suggestions (not required)", never sent to the builder, never re-raised.
3. Re-review may block only on (a) open blocking findings it judges unresolved, or (b) new P0/P1 **inside the interdiff**
   (GitLab Duo / Open SWE rule). A new P0/P1 outside the interdiff goes to S10 as "missed earlier", not into a loop.
4. Builder returns a disposition for every blocking finding: `fixed` (paths + test) | `wont_fix` (reason) | `invalid`
   (reason). `wont_fix`/`invalid` + the reviewer re-raising the same fingerprint → S10, never a third round.
5. Same CI or test failure fingerprint after a fix, or identical open-finding set in two consecutive rounds → S10
   ("no progress").
6. Cap: T1 one review-fix round, T2/T3 two; then S10 with the open ledger. (Bugbot caps Autofix at 3 per PR,
   CodeRabbit pauses after 5 reviewed commits, this repo's own red line is 3 rounds.)

Expected effect versus today (**inferred**): most issues-to-PRs here are T1/T2 → 1 review call + at most 1–2
interdiff re-reviews that can only block on P0/P1; P2/P3 and pre-existing findings stop generating rounds.

### D.2 Context plan (owner decision applied)
- **Builder:** one Codex thread per issue (`thread_id` in LangGraph state), resumed for S4 retries, CI fixes and review
  fixes; every resumed turn sets `sandbox`, `approval_mode`, `effort` explicitly; fix prompts restate the ledger in
  the user message (B.2.3) and carry raw untrusted text fenced as data or as an `ExternalMessage` joining the turn.
- **Restart rule (code):** if `usage.total.input_tokens / model_context_window > 0.6` before a CI-wait round, or the
  thread has compacted twice, or a no-progress strike fires → start a fresh builder thread from the latest handoff +
  ledger instead of resuming (cost: B.2.4 — a cold 200k-token resume after a > 30-minute wait can cost more than a
  fresh start; quality: B.3 — multi-turn degradation and debugging decay after 2–3 attempts).
- **Reviewer:** fresh, read-only, one thread per lens per round, structured output mirroring the Codex rubric; never
  sees the builder transcript (B.1; owner decision).
- **Measure, don't assume:** after each Codex node record `TurnResult.usage` and `account/usage/read {threadId}` →
  `estimatedUsageCreditsMicros` per thread, and `account/rateLimits/read` → `usedPercent` per run (B.2.5).

### D.3 Minimal handoff schema

**`BuildHandoff`** — the builder's `output_schema` on every builder turn (first build and each fix round). Fields marked
(R) feed the reviewer packet, (P) the PR body, (F) the next fix round.

| Field | Type | Seen in (B.4) | Use |
|---|---|---|---|
| `status` | `done \| blocked \| partial` | OpenHands `success`, Copilot | routing (R F) |
| `summary` | ≤ 5 bullets, what + why, for a reader who has not seen the diff | Devin, Codex, Open SWE, Copilot | (P) — withheld from the reviewer |
| `approach` | ≤ 3 sentences | Open SWE Description, LangChain SUMMARY | (R P) |
| `decisions[]` | `{decision, alternatives_rejected, reason, evidence}` | ExecPlan Decision Log, this repo's `## Decisions` | (R P) |
| `assumptions[]` | things the issue did not say that the builder assumed | ExecPlan, "interpreted" in this repo's template | (R P) |
| `acceptance[]` | `{criterion, status: met\|partial\|not_met, evidence: test/cmd/file:line}` | Anthropic `feature_list.json` `passes`, Devin human checklist | (P); the reviewer gets the criteria and the `evidence` pointers, **not** the builder's `status` grades |
| `files[]` | `{path, why}` in suggested reading order | Amp handoff file list, PR-Agent priority files, LangChain ARTIFACTS | (R) |
| `tests[]` | `{cmd, result: pass\|fail\|not_run, note}` | Codex `## Testing` ✅/⚠️, Open SWE Test Plan | (P); S4 re-runs them deterministically and the **S4/CI results** (not the builder's claims) go to the reviewer |
| `not_done[]` | gaps, unverified parts, limits | Copilot "could not access", kernel "what could not be done", Claude Code Action | (R P) |
| `risks[]` | `{area, why}` | Bugbot risk level, PR-Agent risk | (R) and `builder_risk_flags` for D.1 |
| `open_questions[]` | must-answer questions for a human | — | S10 if non-empty and blocking |
| `followups[]` | out-of-scope issues noticed (pre-existing bugs) | Codex rubric "pre-existing" | (P) |
| `dispositions[]` (fix rounds) | `{finding_id, decision: fixed\|wont_fix\|invalid, note, paths}` | GraphQL `ADDRESSED/WONT_FIX/INVALID`, Open SWE, Gerrit Done/Ack | (F R P) |

Added by code, never by the model: `issue_ref`, `base_sha`, `head_sha`, `last_reviewed_sha`, diffstat, tier + reasons,
CI result per required check with run links, `review_round`, finding ledger with fingerprints, Codex `thread_id`,
estimated credits, attribution trailer.

**Reviewer packet** (rubric, lens and blocking rule in the reviewer thread's developer instructions; the packet as
the user message or an `ExternalMessage`, with untrusted text fenced as data). Built to inform without anchoring —
fresh reviewers should judge the diff "on its own terms" (Claude Code docs) and judges favour their own family's
output (B.3); SmartBear's author-annotated reviews showed very low defect density, which its authors attribute mainly to
authors fixing defects while annotating rather than to priming — weak support either way:
- **Facts from code:** issue title, acceptance criteria and constraints; `base_sha..head_sha` (or
  `last_reviewed_sha..head_sha` on re-review) and diffstat; tier and lens; S4 local-gate and CI results at `head_sha`.
- **Builder intent, labelled "claims to verify":** `approach`, `decisions` (with rejected alternatives), `assumptions`,
  `not_done`, `risks`, `files` (reading order), `acceptance[].evidence` pointers. These stop the reviewer flagging
  intentional choices (Codex rubric rule 8) and point it at gaps.
- **Withheld:** the builder's `summary` prose, its `acceptance` status grades, its transcript and reasoning.
- **Re-review only:** the open blocking findings with the builder's dispositions and fix SHAs, plus fingerprints of
  non-blocking items already recorded ("do not repeat").

**PR body** (rendered by S5/S9 from state; for this repo it maps onto `.github/pull_request_template.md`):

| Template section | Filled from |
|---|---|
| `## What` | `summary` + `approach` |
| `## Why` | issue link + problem statement from S1 (`Fixes #N` added by code) |
| `## Decisions` | `decisions[]` as "what / alternatives / evidence / what would prove it wrong" |
| `### Not done / interpreted` | `not_done[]` + `assumptions[]` + `followups[]` + non-blocking review suggestions |
| `## Tested how` | `tests[]` + S4 local-gate result + CI checks at `head_sha` (✅/⚠️ with links) + review tier, rounds and finding counts |

Keep the model-written parts between markers (e.g. `<!-- oc2:handoff:begin/end -->`), put a compact machine-readable
state block in an HTML comment for the graph, and keep the body well under GitHub's 65,536-character limit (put long
ledgers in a PR comment that S5 edits in place).

**Fix-round prompt** (user message built by code; self-contained because compaction may have dropped context):
scope (`checks` | `review` | `local_gate`); the blocking ledger `{id, priority, file:lines, title, required:
disposition}`; the CI failure fingerprint and trimmed log (fenced as untrusted data, or an `ExternalMessage` joining
the turn); the acceptance criteria again; rules: new commits only, one disposition per finding id, do not touch
unrelated files, return `BuildHandoff`.

### D.4 S6 decision table — "re-run, fix, proceed and note, or escalate" in code

Runs after the `03` §5.2 classifier returns `failure`, `blocked` or `missing`, for the current `head_sha` only. Rows
are evaluated top to bottom per failing required job (non-required jobs: same rows, but "escalate" becomes "proceed and
note"). Inputs: run/job/step conclusions, annotations, trimmed log tail, base-branch result for the same workflow+job
(C.4), the flaky registry, and counters in state. Grounding in brackets; actions and caps are **I** (design).

| # | Class | Deterministic signal | Action | Cap |
|---|---|---|---|---|
| 1 | Superseded / stale head | `cancelled` + `Canceling since a higher priority waiting request`, or run head ≠ PR head | ignore, wait for the newer run | — [C.2; Open SWE head reset] |
| 2 | Waiting / external | run `action_required` (0 jobs); check from a non-Actions app that we cannot rerun | **escalate** (required) / note (optional) | — [C.1, C.5] |
| 3 | Startup failure | run `startup_failure`, 0 jobs | diff touches `.github/workflows/**` or `.github/actions/**` → **builder** (run URL + diff, no log); else **escalate** | 1 builder round [C.1] |
| 4 | Infra / transient | runner not acquired; runner lost / shutdown; failing step is setup/checkout/install **and** log tail matches the network set; `Failed to download action`; `Docker pull failed`; rate-limit 429 / `x-ratelimit-remaining: 0`; conclusion `stale` | **rerun failed jobs** (after `retry-after` / reset for rate limits, ≥ 1–5 min otherwise); same class again on this head → **escalate** ("CI unavailable") | 1 per class per head [GitLab `runner_*`, Buildkite −1, CircleCI 2×, Jenkins `agent()`] |
| 5 | Timeout | job `cancelled` + annotation `exceeded the maximum execution time of`, or step `has timed out after` | base's same job also times out (or runs ≥ 80% of the limit) → **rerun** + note; else **builder** with a "hang" hint and the last test started | 1 per head [C.1 live] |
| 6 | Resources | `No space left on device` / `ENOSPC`; explicit heap OOM; exit 137 in a `failure` (not `cancelled`) job | 137 alone → **rerun** once, then builder; explicit OOM / disk → **builder** (base green) or **escalate** (base also failing) | 1 per head [Jenkins vs GitLab on 137] |
| 7 | Flaky | failed then passed on this head (attempt N vs N+1), or every failing test id / fingerprint is in the flaky registry | known-flaky → **rerun** once; pass → **proceed and note** (test ids, attempts; registry updated) | 1 per (head, base) [C.3; OpenShift `max_retests_for_sha_and_base: 1`] |
| 8 | Pre-existing | the same workflow + job + failing step (ideally the same test ids) failed on the base tip's latest completed push run, or in 2 of the last 5 base runs — **unless** the diff touches CI/test infrastructure (then row 10) | no builder; **proceed and note** (optional check) or **escalate** with "also red on base" (required check); re-check once when the base SHA changes | 1 re-check per base SHA [Chromium without-patch; LUCI; OpenShift pause] |
| 9 | Mass failure | ≥ 5 failing jobs/suites or ≥ 80% of tests failing | no rerun; an infra signature → row 4; otherwise (base green) → **builder** | — [Chromium ≥ 5; Trunk 80%; Gradle `maxFailures`] |
| 10 | Change-caused | failing build/lint/type/test step, base green, not known-flaky; or exit 126/127 | **builder** with the trimmed log (below) | 1 dispatch per (head, failure fingerprint) [Open SWE: deterministic → no rerun] |
| 11 | Unclassified | nothing above matched | base green → **builder**, flagged "unclassified"; empty/truncated log → one **rerun** first | — [GitLab `unknown_failure`] |

**Counters** (keyed by PR, head SHA, base SHA; stored in LangGraph state):
- automatic reruns: ≤ 2 per head (≤ 1 per class), reset on a new head; **≤ 5 per PR, never reset** (a flapping builder
  cannot loop) [Open SWE 3 per head; OpenShift 3 per SHA; CircleCI 2; Nx 1];
- builder CI-fix rounds: ≤ 3 per PR; the **same failure fingerprint after a builder fix** counts as "no progress" →
  first time a fresh builder thread seeded from the handoff (B.2.6-4, B.3 Debugging Decay), second time → S10;
- one dispatch per idempotency key `sha256(head | class | run_attempt)` [Open SWE].

**Trimmed log for the builder** (extends `03` §5.4): job + step name + exit code; all `failure` annotations; ~60 lines
from the first `error|FAIL|Traceback|panic:` match; the last ~200 lines of the failing step (ANSI and timestamps
stripped); failing test ids from JUnit if uploaded; the class assigned and the base comparison; cap ~16 KB; fenced as
untrusted data. (GitLab Duo reads the last 150 KiB; the Claude Code Action example sends whole logs — both larger than
needed.)

**Ordering with review:** S7 runs only after S6 ends in `success` or "proceed and note"; reviewing code that the CI
fix will change wastes a full review (**I**; this is the main LLM saving in S6 besides never using an LLM to classify).

**What would prove the table wrong** (**I**): many row-10 dispatches that later pass on a plain rerun → flakes are
mislabelled, raise the rerun budget or add fingerprints to the registry; frequent "baseline unknown" → dispatch a
baseline run on the base SHA instead of relying on push runs; disk/OOM varying across runs of the same SHA → rows 6
should rerun first.

---

## E. Open questions and cheap experiments

1. **Plan accounting for cache.** Does the included ChatGPT Pro allowance debit cached input at the published credit
   ratio (10%, 5% on GPT-6.1 Sol), and are cache writes charged? → Run one build + two resumed fix rounds, read
   `account/usage/read {threadId}` and `account/rateLimits/read` before/after each (B.2.5). ~30 min.
2. **Cache lifetime on the ChatGPT backend.** The API documents a 30-minute TTL for GPT-5.6+; the Codex backend is not
   documented. → Resume a 100k-token thread after 5, 20 and 45 minutes and compare `cached_input_tokens` on the first
   request. Decides whether "resume after CI wait" is warm or cold (B.2.4).
3. **What survives remote compaction.** Force `thread.compact()` on a builder thread mid-task, then ask it for the open
   finding ids and the files it changed; compare with state. Confirms rule B.2.6-2 (ledger always restated).
4. **Thresholds.** The 100 / 500 / 1,000-line and 8-file cut-offs are borrowed anchors (Prow, Google, SmartBear).
   Re-fit after ~30 pipeline PRs on: blocking findings per tier, rounds, and defects found later by humans.
5. **Second model family for T3.** Only worth it if A.4's evidence on correlated errors holds for code review and the
   extra login/cost is acceptable; otherwise use distinct lenses on the same model.
6. **Thread resolution policy.** Should S5 resolve GitHub review threads for `fixed` dispositions (bot resolves, like
   Copilot / Claude Code Review) or leave resolution to the human at S9 (Open SWE fix runs)?
7. **T0 for agent PRs.** Is "no LLM review" acceptable for docs/tests-only PRs written by an agent, given the human at
   S9 reviews anyway? (GitHub defaults to an extra approval for agent-authored PRs.)
8. **Which repositories.** Risk-class globs are per repository; the table in D.1 is for this repo only.
