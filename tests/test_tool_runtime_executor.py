"""Исполнитель инструментов: batch, approval, cancel, parallel."""

from __future__ import annotations

from threading import Event

import pytest

from agent_work.tool_runtime.approval import ApprovalSession
from agent_work.tool_runtime.executor import (
    ApprovalPending,
    ToolExecutor,
    ToolInvocation,
    ToolRejected,
)
from agent_work.tool_runtime.permission import PermissionEngine
from agent_work.tool_runtime.registry import ToolRegistry
from agent_work.tool_runtime.spec import SideEffectClass, ToolSpec


def _echo_registry() -> ToolRegistry:
    spec = ToolSpec(
        name="echo",
        description="",
        parameters_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        side_effect=SideEffectClass.NONE,
        allow_parallel=True,
    )
    return ToolRegistry(
        specs={"echo": spec},
        handlers={"echo": lambda a: str(a["message"])},
    )


def test_serial_order_preserved() -> None:
    """Порядок результатов совпадает с порядком вызовов."""
    reg = _echo_registry()
    ex = ToolExecutor(reg)
    invs = [
        ToolInvocation("1", "echo", '{"message":"a"}'),
        ToolInvocation("2", "echo", '{"message":"b"}'),
    ]
    results = ex.execute_serial(invs, ApprovalSession())
    assert [r.content for r in results] == ["a", "b"]


def test_invalid_tool_arguments_json_returns_error() -> None:
    """Невалидный JSON в arguments_json не должен ронять процесс."""
    reg = _echo_registry()
    ex = ToolExecutor(reg)
    inv = ToolInvocation("x", "echo", '{"message": "a"')  # broken JSON
    res = ex.execute_one(inv, ApprovalSession())
    assert res.error is not None
    assert "invalid_tool_arguments" in res.error


def test_approval_pending_then_resume() -> None:
    """ASK → pending → approve → успех."""
    spec = ToolSpec(
        name="w",
        description="",
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        side_effect=SideEffectClass.WRITE,
    )
    reg = ToolRegistry(
        specs={"write_file": spec},
        handlers={
            "write_file": lambda a: f"ok:{a['path']}",
        },
    )
    ex = ToolExecutor(reg, PermissionEngine())
    approvals = ApprovalSession()
    inv = ToolInvocation("c1", "write_file", '{"path":"x.txt","content":"z"}')
    with pytest.raises(ApprovalPending):
        ex.execute_one(inv, approvals)
    approvals.approve("c1")
    res = ex.execute_one(inv, approvals)
    assert res.error is None
    assert "ok:" in res.content


def test_rejected_raises() -> None:
    """После reject — ToolRejected."""
    spec = ToolSpec(
        name="w",
        description="",
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        side_effect=SideEffectClass.WRITE,
    )
    reg = ToolRegistry(
        specs={"write_file": spec},
        handlers={"write_file": lambda a: "no"},
    )
    ex = ToolExecutor(reg, PermissionEngine())
    approvals = ApprovalSession()
    inv = ToolInvocation("c2", "write_file", '{"path":"a","content":"b"}')
    approvals.reject("c2")
    with pytest.raises(ToolRejected):
        ex.execute_one(inv, approvals)


def test_destructive_denied_result() -> None:
    """DENY не вызывает handler — ошибка в результате."""
    spec = ToolSpec(
        name="d",
        description="",
        parameters_schema={"type": "object", "properties": {}},
        side_effect=SideEffectClass.DESTRUCTIVE,
    )
    reg = ToolRegistry(
        specs={"d": spec},
        handlers={"d": lambda a: "should_not_run"},
    )
    ex = ToolExecutor(reg, PermissionEngine())
    res = ex.execute_one(ToolInvocation("x", "d", "{}"), ApprovalSession())
    assert res.error == "permission_denied"


def test_cancel_before_run() -> None:
    """Отмена до исполнения."""
    reg = _echo_registry()
    ex = ToolExecutor(reg)
    ev = Event()
    ev.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        ex.execute_one(
            ToolInvocation("1", "echo", '{"message":"a"}'),
            ApprovalSession(),
            cancel=ev,
        )


def test_parallel_safe_two_echoes() -> None:
    """Два ALLOW + allow_parallel исполняются в пуле."""
    reg = _echo_registry()
    ex = ToolExecutor(reg)
    invs = [
        ToolInvocation("a", "echo", '{"message":"1"}'),
        ToolInvocation("b", "echo", '{"message":"2"}'),
    ]
    out = ex.execute_parallel_safe(invs, ApprovalSession())
    assert {r.content for r in out} == {"1", "2"}
