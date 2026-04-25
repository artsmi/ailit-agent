"""Tests for `ailit project add` (Workflow 9, G9.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ailit.cli import main


def test_project_add_creates_local_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`project add` writes `.ailit/config.yaml` when none exists."""
    proj = tmp_path / "my-proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    rc = main(["project", "add"])
    assert rc == 0
    cfg = proj / ".ailit" / "config.yaml"
    assert cfg.is_file()
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "projects" in data
    assert data["projects"]["entries"][0]["path"] == str(proj.resolve())
    assert data["projects"]["entries"][0]["active"] is True
    assert data["projects"]["active_project_ids"]


def test_project_add_idempotent_by_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second add does not create duplicate entries for same path."""
    proj = tmp_path / "p"
    proj.mkdir()
    monkeypatch.chdir(proj)
    assert main(["project", "add"]) == 0
    assert main(["project", "add", str(proj)]) == 0
    cfg = proj / ".ailit" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    entries = data["projects"]["entries"]
    assert isinstance(entries, list)
    assert len(entries) == 1


def test_project_add_uses_nearest_existing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When parent has `.ailit/config.yaml`, it is used as registry file."""
    root = tmp_path / "ws"
    child = root / "child"
    child.mkdir(parents=True)
    cfg = root / ".ailit" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("schema_version: 1\n", encoding="utf-8")
    monkeypatch.chdir(child)
    assert main(["project", "add"]) == 0
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "projects" in data
    assert data["projects"]["entries"]


def test_project_add_invalid_path_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid path returns exit code 2 and prints error."""
    monkeypatch.chdir(tmp_path)
    rc = main(["project", "add", str(tmp_path / "missing")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Некорректный путь проекта" in err
