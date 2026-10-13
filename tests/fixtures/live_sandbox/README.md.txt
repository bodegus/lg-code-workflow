# lgcw live qualification fixture

A minimal addition CLI with canonical release metadata and real GitHub Actions CI. This fixture
exists to prove that lgcw can build a bounded version bump, run local checks, publish safely,
observe CI, review in a fresh agent session, and stop with a merge-ready PR.

The initial version is `0.1.0`. Tests validate arithmetic and CLI behavior and ensure `--version`
matches `VERSION`, so patch bumps need no weakened assertions or test edits.

The fixture is not evidence of qualification until the complete real workflow has run.
