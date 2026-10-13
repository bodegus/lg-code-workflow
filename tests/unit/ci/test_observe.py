"""Required-policy unions and trusted infrastructure signal boundaries."""

from __future__ import annotations

import pytest

from lgcw.ci.decide import decide
from lgcw.ci.observe import effective_required
from lgcw.models.config import Limits
from tests.unit.ci.cases import SHA, history, job, repo, required, run


@pytest.mark.unit
@pytest.mark.parametrize(
    "text", ["runner lost connection", "failed to download image", "action download failed"]
)
def test_application_log_prose_cannot_authorize_infrastructure_rerun(text: str) -> None:
    decision = decide(
        "failure",
        [job()],
        [run()],
        [job(conclusion="success")],
        history(),
        [],
        {1: text},
        repo(),
        Limits(),
        pushed_sha=SHA,
    )
    assert (decision.klass, decision.action) == ("change", "fix")


@pytest.mark.unit
@pytest.mark.parametrize("observed", [False, True])
def test_required_ruleset_context_is_never_dropped(observed: bool) -> None:
    checks = effective_required(
        required(),
        ("security",),
        [run(workflow="Security")],
        [job(workflow="Security", name="security")] if observed else [],
    )
    pairs = {(check.workflow, check.job) for check in checks}
    assert ("CI", "test") in pairs and ("Security", "security") in pairs


@pytest.mark.unit
def test_required_unobserved_context_without_runs_stays_required() -> None:
    checks = effective_required(required(), ("security",), [], [])
    assert any(check.job == "security" for check in checks)
