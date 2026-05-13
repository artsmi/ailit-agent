"""Тесты bash_runner (этап B)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from agent_work.bash_runner import BashRunOutcome, run_bash_command

pytestmark = pytest.mark.skipif(
    not shutil.which("bash"),
    reason="bash not on PATH",
)


def test_run_bash_echo(tmp_path: Path) -> None:
    root = tmp_path
    out = run_bash_command("echo hi", cwd=root, timeout_ms=5_000)
    assert isinstance(out, BashRunOutcome)
    assert out.exit_code == 0
    assert "hi" in out.stdout
    assert out.timed_out is False
    assert out.truncated is False
    assert out.spill_path is None


def test_run_bash_exit_nonzero(tmp_path: Path) -> None:
    root = tmp_path
    out = run_bash_command("exit 7", cwd=root, timeout_ms=5_000)
    assert out.exit_code == 7
    assert out.timed_out is False


@pytest.mark.skipif(sys.platform == "win32", reason="killpg semantics")
def test_run_bash_timeout(tmp_path: Path) -> None:
    root = tmp_path
    out = run_bash_command("sleep 10", cwd=root, timeout_ms=200)
    assert out.timed_out is True
    assert out.exit_code is None


def test_run_bash_truncation_spill(tmp_path: Path) -> None:
    root = tmp_path
    out = run_bash_command(
        "for _ in {1..400}; do echo xxxxxxxxxx; done",
        cwd=root,
        timeout_ms=30_000,
        max_capture_bytes=2_000,
    )
    assert out.truncated is True
    assert out.spill_path is not None
    spill = root / ".ailit"
    assert spill.is_dir()
