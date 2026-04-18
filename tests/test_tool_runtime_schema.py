"""Схема и сериализация ToolSpec."""

from __future__ import annotations

import pytest
from jsonschema import ValidationError

from agent_core.tool_runtime.schema_validate import parse_and_validate_arguments_json, validate_tool_arguments
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec


def test_validate_rejects_wrong_type() -> None:
    """Несоответствие типа аргумента."""
    spec = ToolSpec(
        name="t",
        description="d",
        parameters_schema={
            "type": "object",
            "properties": {"n": {"type": "number"}},
            "required": ["n"],
        },
    )
    with pytest.raises(ValidationError):
        validate_tool_arguments(spec, {"n": "x"})


def test_parse_and_validate_json() -> None:
    """JSON строка парсится и валидируется."""
    spec = ToolSpec(
        name="echo",
        description="d",
        parameters_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    out = parse_and_validate_arguments_json(spec, '{"message":"hi"}')
    assert out == {"message": "hi"}


def test_tool_spec_roundtrip_dict() -> None:
    """Сериализация ToolSpec туда-обратно."""
    orig = ToolSpec(
        name="x",
        description="dx",
        parameters_schema={"type": "object", "properties": {}},
        side_effect=SideEffectClass.READ,
        requires_approval=True,
        allow_parallel=False,
        metadata={"k": 1},
    )
    restored = ToolSpec.from_dict(orig.to_dict())
    assert restored == orig
