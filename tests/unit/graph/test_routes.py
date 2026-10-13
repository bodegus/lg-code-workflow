"""Every router is a pure projection of the explicit next step."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from lgcw.graph.routes import ROUTERS
from lgcw.models.base import Step
from lgcw.models.issue import IssueRef
from lgcw.models.state import RunState


@pytest.mark.unit
@pytest.mark.parametrize("step", TypeAdapter(Step).json_schema()["enum"])
def test_routers_project_explicit_step(step: Step) -> None:
    state = RunState(issue_ref=IssueRef(repo="example/sandbox", number=1), next_step=step)
    assert len(ROUTERS) == 8 and all(router(state) == step for router in ROUTERS)
