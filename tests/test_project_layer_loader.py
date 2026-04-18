"""Загрузка project.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from project_layer.loader import load_project, load_project_mapping
from project_layer.models import RuntimeMode


def test_load_repo_project_yaml() -> None:
    """Корневой project.yaml репозитория парсится."""
    root = Path(__file__).resolve().parents[1]
    loaded = load_project(root / "project.yaml")
    assert loaded.config.project_id == "ailit_agent"
    assert loaded.config.runtime is RuntimeMode.AILIT
    assert "minimal" in loaded.config.workflows


def test_invalid_runtime() -> None:
    """Неверный runtime даёт ValueError."""
    raw = {"project_id": "x", "runtime": "unknown"}
    with pytest.raises(ValueError, match="invalid runtime"):
        load_project_mapping(raw)


def test_workflow_requires_path(tmp_path: Path) -> None:
    """Workflow без path — ValueError."""
    p = tmp_path / "project.yaml"
    p.write_text(
        yaml.safe_dump({"project_id": "p", "workflows": {"w": {}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must contain 'path'"):
        load_project(p)
