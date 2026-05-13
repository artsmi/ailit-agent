"""Selective tool exposure (M3): фильтрация схемы tools."""

from __future__ import annotations

from agent_work.session.tool_exposure import tool_definitions_exposed
from agent_work.tool_runtime.bash_tools import bash_tool_registry
from agent_work.tool_runtime.registry import default_builtin_registry


def test_read_only_drops_write_and_shell() -> None:
    reg = default_builtin_registry().merge(bash_tool_registry())
    defs = tool_definitions_exposed(reg, "read_only")
    names = {d.name for d in defs}
    assert "read_file" in names
    assert "write_file" not in names
    assert "run_shell" not in names


def test_filesystem_keeps_read_path_tools_only() -> None:
    reg = default_builtin_registry().merge(bash_tool_registry())
    defs = tool_definitions_exposed(reg, "filesystem")
    names = {d.name for d in defs}
    assert "read_file" in names
    assert "write_file" not in names
    assert "run_shell" not in names
    assert "list_dir" in names
