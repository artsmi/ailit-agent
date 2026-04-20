"""Тесты `ailit setup` и `ailit models` (DP-2 утилиты)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ailit.cli import main


def test_setup_non_interactive_writes_global_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`setup --non-interactive` пишет в глобальный config.yaml."""
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg))
    rc = main(
        [
            "setup",
            "--non-interactive",
            "--provider",
            "deepseek",
            "--model",
            "deepseek-chat",
            "--api-key",
            "k",
        ]
    )
    assert rc == 0
    assert (cfg / "config.yaml").is_file()


def test_models_list_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`models list` печатает провайдеров."""
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(tmp_path / "cfg"))
    rc = main(["models", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[deepseek]" in out
    assert "[kimi]" in out
