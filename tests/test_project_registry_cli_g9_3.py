"""Tests: `ailit project add` (G9.3), глобальный ``~/.ailit``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ailit.cli import main
from ailit.global_ailit_layout import (
    user_global_config_path,
    user_projects_root,
)


def test_project_add_creates_global_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`project add` пишет в ``$HOME/.ailit``."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "my-proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    rc = main(["project", "add"])
    assert rc == 0
    g = user_global_config_path()
    assert g.is_file()
    gdata = yaml.safe_load(g.read_text(encoding="utf-8"))
    assert gdata.get("active_project_ids")
    proot = user_projects_root()
    assert proot.is_dir()
    pdirs = [p for p in proot.iterdir() if p.is_dir()]
    assert len(pdirs) == 1
    pcfg = pdirs[0] / "config.yaml"
    assert pcfg.is_file()
    row = yaml.safe_load(pcfg.read_text(encoding="utf-8"))
    assert row["path"] == str(proj.resolve())
    assert row["active"] is True


def test_project_add_idempotent_by_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Второй add того же path не плодит дубликатов в списке проектов."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "p"
    proj.mkdir()
    monkeypatch.chdir(proj)
    assert main(["project", "add"]) == 0
    assert main(["project", "add", str(proj)]) == 0
    g = user_global_config_path()
    gdata = yaml.safe_load(g.read_text(encoding="utf-8"))
    ap = gdata.get("active_project_ids", [])
    assert ap == list(dict.fromkeys(ap))  # уникальны
    proot = user_projects_root()
    n_dirs = len([d for d in proot.iterdir() if d.is_dir()])
    assert n_dirs == 1


def test_project_add_separate_repos_separate_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Два разных пути — две папки в ``projects/``."""
    monkeypatch.setenv("HOME", str(tmp_path))
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.chdir(a)
    assert main(["project", "add"]) == 0
    monkeypatch.chdir(b)
    assert main(["project", "add"]) == 0
    n = len([d for d in user_projects_root().iterdir() if d.is_dir()])
    assert n == 2


def test_project_add_invalid_path_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid path returns exit code 2 and prints error."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    rc = main(["project", "add", str(tmp_path / "missing")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Некорректный путь проекта" in err


def test_project_list_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`project list --json` без --start, один JSON."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "repo"
    proj.mkdir()
    monkeypatch.chdir(proj)
    assert main(["project", "add"]) == 0
    capsys.readouterr()
    assert main(["project", "list", "--json"]) == 0
    out = capsys.readouterr().out
    assert "registry_file" in out
    assert "active_project_ids" in out
    assert "entries" in out
