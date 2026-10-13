"""Package contract."""

from __future__ import annotations

import pytest

import lgcw


@pytest.mark.unit
def test_version() -> None:
    assert lgcw.__version__ == "0.1.0"
