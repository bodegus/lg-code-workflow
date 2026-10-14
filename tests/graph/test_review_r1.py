"""Real-git review regressions for critical findings on unmatched locations."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from lgcw.graph.runner import run_issue
from lgcw.models.harness import Role
from lgcw.models.review import CodeLocation, LineRange, ReviewVerdict
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import markers, output, setup
from tests.graph.test_review_loop import ReviewHarness, calls
from tests.unit.ci.cases import job, run


class LocatedHarness(ReviewHarness):
    """Rebind scripted reviewer locations at the fake port boundary."""

    path = "app.py"
    location = "valid"

    def script(self, role: Role, outputs: list[BaseModel | Exception]) -> None:
        rebound: list[BaseModel | Exception] = []
        for value in outputs:
            if role == "reviewer" and isinstance(value, ReviewVerdict):
                findings = []
                for finding in value.findings:
                    root = Path(finding.code_location.absolute_file_path).parent
                    path = (
                        root / self.path
                        if self.location != "outside"
                        else root.parent / "foreign.py"
                    )
                    line = 200 if self.location == "line" else 1
                    findings.append(
                        finding.model_copy(
                            update={
                                "confidence_score": 0.99,
                                "code_location": CodeLocation(
                                    absolute_file_path=str(path),
                                    line_range=LineRange(start=line, end=line),
                                ),
                            }
                        )
                    )
                value = value.model_copy(
                    update={"findings": findings, "overall_explanation": "R1 location evidence."}
                )
            rebound.append(value)
        super().script(role, rebound)


@pytest.mark.unit
@pytest.mark.parametrize("location", ["valid", "outside", "line"])
async def test_critical_location_cannot_disappear(graph_case: GraphCase, location: str) -> None:
    path = "my file.py" if location == "valid" else "app.py"
    edits = [{path: "VERSION = '0.1.1'\n"}, {path: "VERSION = '0.1.2'\n"}]
    ctx, old = await setup(graph_case, edits, [])
    harness = LocatedHarness(old.root, edits, [0, None])
    harness.path, harness.location = path, location
    harness.script("builder", [output(path), output(path)])

    def passing(head: str) -> None:
        graph_case.github.runs[head] = [run(head=head)]
        graph_case.github.jobs[1] = [job(conclusion="success")]

    graph_case.workspace.after_push = passing
    ctx = ctx.model_copy(update={"harness": harness})
    if location != "valid":
        graph_case.github.fail_after("create_review", 1, InjectedCrash("review response lost"))
        with pytest.raises(InjectedCrash):
            await run_issue(ctx)
    assert await run_issue(ctx) == ("merge_ready" if location == "valid" else "waiting")
    review_body = graph_case.github.reviews[(ctx.issue_ref.repo, 100)][0].body
    assert "patch is incorrect" in review_body and "R1 location evidence." in review_body
    if location == "valid":
        assert [session.role for session, _ in harness.turns] == [
            "builder",
            "reviewer",
            "builder",
            "reviewer",
        ]
    else:
        assert len(harness.turns) == 2 and calls(graph_case, "mark_ready") == 0
        assert markers(graph_case, "ask")[-1].code == "review_evidence_missing"
        assert await run_issue(ctx) == "waiting" and len(harness.turns) == 2
