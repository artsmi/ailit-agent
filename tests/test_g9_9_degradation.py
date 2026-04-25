"""G9.9.2: деградации и отказоустойчивость CLI/runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from ailit.cli import main


def test_g9_9_runtime_status_no_supervisor_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Нет сокета supervisor: exit 2, подсказка systemctl/journalctl."""
    rd = tmp_path / "no-runtime"
    rd.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rd))
    assert main(["runtime", "status"]) == 2
    _, err = capfd.readouterr()
    assert "Supervisor socket" in err
    assert "systemctl" in err


def test_g9_9_runtime_brokers_no_supervisor_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """`runtime brokers` без сокета: exit 2."""
    rd = tmp_path / "no-runtime-2"
    rd.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rd))
    assert main(["runtime", "brokers"]) == 2
    _, err = capfd.readouterr()
    assert "Supervisor socket" in err


def test_g9_9_memory_pag_slice_bad_level_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Некорректный --level у pag-slice: ok=false, exit 2."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert (
        main(
            [
                "memory",
                "pag-slice",
                "--namespace",
                "any",
                "--level",
                "Z",
            ]
        )
        == 2
    )
    out, _ = capfd.readouterr()
    assert "ok" in out
    assert "bad_args" in out or "error" in out


def test_g9_9_project_add_invalid_path_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Invalid project path: exit 2, сообщение на русском."""
    monkeypatch.chdir(tmp_path)
    assert main(["project", "add", str(tmp_path / "nope")]) == 2
    _, err = capfd.readouterr()
    assert "Некорректный путь" in err
