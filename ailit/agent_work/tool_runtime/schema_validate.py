"""Валидация аргументов инструмента по JSON Schema."""

from __future__ import annotations

import json
from typing import Any, Mapping

from jsonschema import Draft7Validator, ValidationError

from agent_work.tool_runtime.spec import ToolSpec


def validate_tool_arguments(spec: ToolSpec, arguments: Mapping[str, Any]) -> None:
    """Бросить ValidationError, если аргументы не соответствуют схеме."""
    schema = dict(spec.parameters_schema)
    if not schema:
        schema = {"type": "object"}
    elif "type" not in schema and "properties" in schema:
        schema = {"type": "object", **schema}
    validator = Draft7Validator(schema)
    validator.validate(dict(arguments))


def parse_and_validate_arguments_json(spec: ToolSpec, arguments_json: str) -> dict[str, Any]:
    """Распарсить JSON и провалидировать."""
    try:
        raw = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        raise ValueError("tool arguments must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("tool arguments JSON root must be object")
    validate_tool_arguments(spec, raw)
    return raw
