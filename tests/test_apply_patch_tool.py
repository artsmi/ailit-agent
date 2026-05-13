"""Unit: apply_patch, multi-root, atomic semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_work.session.mode_permission_policy import ModePermissionPolicy
from agent_work.tool_runtime.bash_tools import bash_tool_registry
from agent_work.tool_runtime.builtins import (
    builtin_apply_patch,
    builtin_tool_specs,
)
from agent_work.tool_runtime.executor import ToolInvocation
from agent_work.tool_runtime.multi_root_paths import (
    resolve_absolute_file_under_work_roots,
    work_roots,
)
from agent_work.tool_runtime.permission import PermissionDecision
from agent_work.tool_runtime.registry import default_builtin_registry


def test_work_roots_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv(
        "AILIT_WORK_ROOTS",
        json.dumps([str(a.resolve()), str(b.resolve())]),
    )
    monkeypatch.delenv("AILIT_WORK_ROOT", raising=False)
    roots = work_roots()
    assert len(roots) == 2
    f = a / "f.txt"
    f.write_text("h", encoding="utf-8")
    p, rel = resolve_absolute_file_under_work_roots(str(f))
    assert rel == "f.txt"
    p2, rel2 = resolve_absolute_file_under_work_roots(str(f.resolve()))
    assert rel2 == "f.txt"


def test_apply_patch_create_and_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "p"
    root.mkdir()
    monkeypatch.setenv("AILIT_WORK_ROOT", str(root.resolve()))
    monkeypatch.delenv("AILIT_WORK_ROOTS", raising=False)
    nf = root / "new.md"
    builtin_apply_patch(
        {
            "filePath": str(nf),
            "oldString": "",
            "newString": "# t\n",
        },
    )
    assert nf.read_text(encoding="utf-8") == "# t\n"
    builtin_apply_patch(
        {
            "filePath": str(nf),
            "oldString": "# t",
            "newString": "# x",
        },
    )
    assert "# x" in nf.read_text(encoding="utf-8")


def test_apply_patch_rejects_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "p"
    root.mkdir()
    monkeypatch.setenv("AILIT_WORK_ROOT", str(root.resolve()))
    f = root / "a.txt"
    f.write_text("one", encoding="utf-8")
    with pytest.raises(ValueError, match="oldString not found"):
        builtin_apply_patch(
            {
                "filePath": str(f),
                "oldString": "nope",
                "newString": "x",
            },
        )


def test_read_mode_denies_apply_patch() -> None:
    reg = default_builtin_registry().merge(bash_tool_registry())
    spec = reg.specs["apply_patch"]
    pol = ModePermissionPolicy("read")
    p = str(Path("/tmp/will-not-resolve-in-test").resolve())
    inv = ToolInvocation(
        "1",
        "apply_patch",
        json.dumps(
            {
                "filePath": p,
                "oldString": "",
                "newString": "a",
            },
        ),
    )
    assert pol.evaluate(spec, inv) is PermissionDecision.DENY


def test_apply_patch_spec_present() -> None:
    specs = builtin_tool_specs()
    assert "apply_patch" in specs
    assert specs["apply_patch"].name == "apply_patch"
