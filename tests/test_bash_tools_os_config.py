"""Allowlist и env-лимиты для ``builtin_run_shell``."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_core.tool_runtime.bash_tools import (
    BashToolOsConfig,
    builtin_run_shell,
)

pytestmark = pytest.mark.skipif(
    not shutil.which("bash"),
    reason="bash not on PATH",
)


def test_allow_patterns_json_blocks_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """При allowlist команда вне шаблонов отклоняется до subprocess."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "AILIT_BASH_ALLOW_PATTERNS_JSON",
        json.dumps(["echo *"]),
    )
    cfg = BashToolOsConfig.current()
    assert cfg.allow_patterns == ("echo *",)
    with pytest.raises(ValueError, match="allow_patterns"):
        builtin_run_shell({"command": "git status"})


def test_allow_patterns_allows_fnmatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Команда, совпавшая с fnmatch, выполняется."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "AILIT_BASH_ALLOW_PATTERNS_JSON",
        json.dumps(["echo *"]),
    )
    out = builtin_run_shell({"command": "echo ok"})
    assert "exit_code: 0" in out
    assert "ok" in out


def test_default_timeout_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Env AILIT_BASH_DEFAULT_TIMEOUT_MS, если timeout_ms не передан."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    monkeypatch.setenv("AILIT_BASH_DEFAULT_TIMEOUT_MS", "5000")
    out = builtin_run_shell({"command": "echo t"})
    assert "exit_code: 0" in out
    assert "t" in out
