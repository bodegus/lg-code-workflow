"""Strict output-schema contracts, including nested objects."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from lgcw.models.base import SchemaNotStrictError, Strict, strict_json_schema
from lgcw.models.handoff import BuildHandoff
from lgcw.models.issue import IssueRef
from lgcw.models.review import FindingCheck, ReviewVerdict


@pytest.mark.unit
def test_strict_schema_build_handoff_is_strict() -> None:
    schema = strict_json_schema(BuildHandoff)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(BuildHandoff.model_fields)


@pytest.mark.unit
@pytest.mark.parametrize("model", [BuildHandoff, ReviewVerdict, FindingCheck])
def test_agent_schemas_are_strict(model: type[BaseModel]) -> None:
    schema = strict_json_schema(model)
    for definition in schema.get("$defs", {}).values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
            assert set(definition["required"]) == set(definition["properties"])


@pytest.mark.unit
def test_strict_schema_rejects_defaults() -> None:
    class Loose(Strict):
        x: int = 1

    with pytest.raises(SchemaNotStrictError):
        strict_json_schema(Loose)


@pytest.mark.unit
def test_strict_schema_rejects_nested_defaults() -> None:
    class Child(Strict):
        x: int = 1

    class Parent(Strict):
        children: list[Child] | None

    with pytest.raises(SchemaNotStrictError):
        strict_json_schema(Parent)


@pytest.mark.unit
def test_strict_schema_rejects_open_objects() -> None:
    class OpenObject(BaseModel):
        x: str

    class Parent(Strict):
        child: OpenObject

    with pytest.raises(SchemaNotStrictError):
        strict_json_schema(Parent)


@pytest.mark.unit
def test_strict_schema_rejects_missing_required_property() -> None:
    class Loose(Strict):
        model_config = ConfigDict(json_schema_extra={"required": []})
        x: str

    with pytest.raises(SchemaNotStrictError):
        strict_json_schema(Loose)


@pytest.mark.unit
def test_property_named_default_is_allowed() -> None:
    class NamedDefault(Strict):
        default: str

    assert strict_json_schema(NamedDefault)["required"] == ["default"]


@pytest.mark.unit
def test_nullable_fields_still_must_be_present() -> None:
    class Nullable(Strict):
        value: str | None

    assert strict_json_schema(Nullable)["required"] == ["value"]
    assert Nullable(value=None).value is None
    with pytest.raises(ValidationError):
        Nullable.model_validate({})


@pytest.mark.unit
def test_default_rejected_even_when_schema_marks_property_required() -> None:
    class Defaulted(Strict):
        model_config = ConfigDict(json_schema_extra={"required": ["value"]})
        value: int = 1

    with pytest.raises(SchemaNotStrictError, match="defaults are forbidden"):
        strict_json_schema(Defaulted)


@pytest.mark.unit
def test_models_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        IssueRef.model_validate({"repo": "a/b", "number": 1, "x": 1})


@pytest.mark.unit
@pytest.mark.parametrize(("attribute", "replacement"), [("repo", "c/d"), ("number", 2)])
def test_models_are_frozen(attribute: str, replacement: str | int) -> None:
    issue = IssueRef(repo="a/b", number=1)
    with pytest.raises(ValidationError, match="frozen"):
        setattr(issue, attribute, replacement)
