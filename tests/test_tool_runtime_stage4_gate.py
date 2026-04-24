"""Тест этапа 4: read-only, write (approval), deny."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.executor import ApprovalPending, ToolExecutor, ToolInvocation
from agent_core.tool_runtime.permission import PermissionEngine
from agent_core.tool_runtime.registry import ToolRegistry, default_builtin_registry
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec


@pytest.fixture
def tmp_work_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированный AILIT_WORK_ROOT."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    (tmp_path / "hello.txt").write_text("world", encoding="utf-8")
    return tmp_path


def test_read_write_destructive_scenario(tmp_work_root: Path) -> None:
    """read_file без approval; write_file с approval; destructive — deny."""
    reg = default_builtin_registry()
    perm = PermissionEngine()
    ex = ToolExecutor(reg, perm)
    approvals = ApprovalSession()

    r1 = ex.execute_one(
        ToolInvocation("r1", "read_file", '{"path":"hello.txt"}'),
        approvals,
    )
    assert r1.error is None
    assert "world" in (r1.content or "")
    assert "ailit:read_meta" in (r1.content or "")

    w_inv = ToolInvocation("w1", "write_file", '{"path":"out.txt","content":"x"}')
    with pytest.raises(ApprovalPending):
        ex.execute_one(w_inv, approvals)
    approvals.approve("w1")
    w1 = ex.execute_one(w_inv, approvals)
    assert w1.error is None
    assert (tmp_work_root / "out.txt").read_text() == "x"

    danger = ToolSpec(
        name="danger",
        description="",
        parameters_schema={"type": "object", "properties": {}},
        side_effect=SideEffectClass.DESTRUCTIVE,
    )

    reg2 = ToolRegistry(
        specs={**reg.specs, "danger": danger},
        handlers={**reg.handlers, "danger": lambda a: "boom"},
    )
    ex2 = ToolExecutor(reg2, perm)
    d = ex2.execute_one(ToolInvocation("d1", "danger", "{}"), approvals)
    assert d.error == "permission_denied"
