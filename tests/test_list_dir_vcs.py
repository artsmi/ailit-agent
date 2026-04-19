"""Правила list_dir вокруг каталогов VCS (явный ``.git`` vs корень проекта)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.tool_runtime.builtins import builtin_list_dir


@pytest.fixture
def work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Задать ``AILIT_WORK_ROOT`` на временный проект."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path.resolve()))
    return tmp_path


def test_list_dir_git_shows_immediate_children(work: Path) -> None:
    """Явный ``list_dir`` на ``.git`` не даёт пустой списка из-за фильтра по сегменту."""
    (work / ".git" / "hooks").mkdir(parents=True)
    (work / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    out = json.loads(builtin_list_dir({"path": ".git"}))
    names = {e["name"] for e in out["entries"]}
    assert "hooks" in names
    assert "HEAD" in names


def test_list_dir_project_root_hides_dot_git(work: Path) -> None:
    """В корне проекта каталог ``.git`` не показываем (шум для модели)."""
    (work / ".git").mkdir()
    (work / "README.md").write_text("hi", encoding="utf-8")
    out = json.loads(builtin_list_dir({"path": "."}))
    names = {e["name"] for e in out["entries"]}
    assert ".git" not in names
    assert "README.md" in names


def test_list_dir_nested_subdir_still_hides_git_folder(work: Path) -> None:
    """В обычной вложенной папке по-прежнему скрываем вложенный ``.git``."""
    sub = work / "pkg"
    sub.mkdir()
    (sub / ".git").mkdir()
    (sub / "a.py").write_text("1", encoding="utf-8")
    out = json.loads(builtin_list_dir({"path": "pkg"}))
    names = {e["name"] for e in out["entries"]}
    assert ".git" not in names
    assert "a.py" in names
