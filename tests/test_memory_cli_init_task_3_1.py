"""TC-3_1: ``ailit memory init`` help и неверный path."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ailit_cli.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_E2E_DIR = _REPO_ROOT / "tests" / "e2e"
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from cli_runner import AilitCliRunner  # noqa: E402


def test_tc_3_1_help_memory_init() -> None:
    """TC-3_1-HELP: subprocess, синтаксис с path, exit 0."""
    runner = AilitCliRunner(_REPO_ROOT)
    cmd: list[str] = [
        runner._python(),
        "-m",
        "ailit_cli.cli",
        "memory",
        "init",
        "--help",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        env=runner._env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0
    combined = (proc.stdout or "") + (proc.stderr or "")
    lowered = combined.lower()
    assert "path" in lowered
    assert "init" in lowered


def test_tc_3_1_invalid_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """TC-3_1-INVALID-PATH: несуществующий каталог → non-zero и сообщение."""
    missing = tmp_path / "not_a_real_project_dir"
    rc = main(["memory", "init", str(missing)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "memory_init_root_missing" in err or "does not exist" in err
