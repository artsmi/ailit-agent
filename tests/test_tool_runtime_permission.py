"""Permission allow / ask / deny."""

from __future__ import annotations

import pytest

from agent_core.tool_runtime.permission import PermissionDecision, PermissionEngine
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec


def test_read_only_allowed() -> None:
    """READ_ONLY по умолчанию ALLOW."""
    eng = PermissionEngine()
    spec = ToolSpec(
        name="r",
        description="",
        parameters_schema={"type": "object", "properties": {}},
        side_effect=SideEffectClass.READ_ONLY,
    )
    assert eng.evaluate(spec) is PermissionDecision.ALLOW


def test_write_asks() -> None:
    """WRITE по умолчанию ASK."""
    eng = PermissionEngine()
    spec = ToolSpec(
        name="w",
        description="",
        parameters_schema={"type": "object", "properties": {}},
        side_effect=SideEffectClass.WRITE,
    )
    assert eng.evaluate(spec) is PermissionDecision.ASK


def test_destructive_denied_by_default() -> None:
    """DESTRUCTIVE по умолчанию DENY."""
    eng = PermissionEngine()
    spec = ToolSpec(
        name="d",
        description="",
        parameters_schema={"type": "object", "properties": {}},
        side_effect=SideEffectClass.DESTRUCTIVE,
    )
    assert eng.evaluate(spec) is PermissionDecision.DENY


def test_requires_approval_forces_ask() -> None:
    """Флаг requires_approval переводит в ASK даже при READ_ONLY."""
    eng = PermissionEngine()
    spec = ToolSpec(
        name="q",
        description="",
        parameters_schema={"type": "object", "properties": {}},
        side_effect=SideEffectClass.READ_ONLY,
        requires_approval=True,
    )
    assert eng.evaluate(spec) is PermissionDecision.ASK
