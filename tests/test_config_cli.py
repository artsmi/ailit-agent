"""Тесты подкоманд ``ailit config`` и редактора секретов."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ailit.cli import main
from ailit.config_secrets import ConfigSecretRedactor
from ailit.project_root_hint import ProjectRootDetector


def test_secret_redactor_masks_api_key() -> None:
    """Ключи с ``api_key`` маскируются, остальная структура сохраняется."""
    raw = {
        "deepseek": {"api_key": "secret", "model": "m"},
        "kimi": {"api_key": "x"},
    }
    out = ConfigSecretRedactor().redact(raw)
    assert out["deepseek"]["api_key"] == "***REDACTED***"
    assert out["deepseek"]["model"] == "m"
    assert out["kimi"]["api_key"] == "***REDACTED***"
    assert raw["deepseek"]["api_key"] == "secret"


def test_project_root_detector_finds_project_yaml(tmp_path: Path) -> None:
    """Обнаружение ``project.yaml`` в корне."""
    (tmp_path / "project.yaml").write_text("project_id: x\n", encoding="utf-8")
    assert ProjectRootDetector().find(tmp_path) == tmp_path.resolve()


def test_project_root_detector_finds_ailit_config(tmp_path: Path) -> None:
    """Обнаружение ``.ailit/config.yaml``."""
    cfg = tmp_path / ".ailit" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("deepseek: {}\n", encoding="utf-8")
    assert ProjectRootDetector().find(tmp_path) == tmp_path.resolve()


def test_config_path_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``config path`` печатает каталоги и не падает."""
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(tmp_path / "g"))
    monkeypatch.delenv("AILIT_STATE_DIR", raising=False)
    rc = main(["config", "path"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AILIT_HOME=" in out
    assert "global_config_dir=" in out
    assert "global_state_dir=" in out
    assert "global_logs_dir=" in out
    assert "global_config_file=" in out
    assert "detected_project_root=" in out


def test_config_show_redacts_in_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``config show`` не печатает сырое значение api_key."""
    cfg_home = tmp_path / "cfg"
    cfg_home.mkdir()
    (cfg_home / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"api_key": "super-secret", "model": "z"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_home))
    monkeypatch.chdir(tmp_path)
    rc = main(["config", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "super-secret" not in out
    assert "***REDACTED***" in out
    assert "z" in out
