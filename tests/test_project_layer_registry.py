"""Реестр workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from project_layer.loader import LoadedProject, load_project
from project_layer.models import WorkflowRef, project_config_from_mapping
from project_layer.registry import ProjectRegistries


def test_resolve_workflow_id(tmp_path: Path) -> None:
    """Id резолвится в файл относительно корня."""
    wf = tmp_path / "w.yaml"
    wf.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "t",
                "stages": [{"id": "s", "tasks": [{"id": "a", "system_prompt": "x", "user_text": "y"}]}],
            },
        ),
        encoding="utf-8",
    )
    proj = tmp_path / "project.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "project_id": "demo",
                "workflows": {"main": {"path": "w.yaml"}},
            },
        ),
        encoding="utf-8",
    )
    loaded = load_project(proj)
    reg = ProjectRegistries(loaded)
    assert reg.workflow_path("main") == wf.resolve()


def test_resolve_relative_yaml_path(tmp_path: Path) -> None:
    """Путь *.yaml относительно корня проекта."""
    wf = tmp_path / "sub" / "x.yaml"
    wf.parent.mkdir(parents=True)
    wf.write_text("workflow_id: z\nstages: []\n", encoding="utf-8")
    proj = tmp_path / "project.yaml"
    proj.write_text(yaml.safe_dump({"project_id": "demo"}), encoding="utf-8")
    loaded = load_project(proj)
    reg = ProjectRegistries(loaded)
    with pytest.raises(KeyError):
        reg.workflow_path("missing")

    p = reg.workflow_path("sub/x.yaml")
    assert p == wf.resolve()


def test_absolute_yaml_path(tmp_path: Path) -> None:
    """Абсолютный путь к yaml."""
    wf = tmp_path / "abs.yaml"
    wf.write_text("workflow_id: z\nstages: []\n", encoding="utf-8")
    proj = tmp_path / "project.yaml"
    proj.write_text(yaml.safe_dump({"project_id": "demo"}), encoding="utf-8")
    loaded = load_project(proj)
    reg = ProjectRegistries(loaded)
    assert reg.workflow_path(str(wf)) == wf.resolve()


def test_list_workflows() -> None:
    """Список ссылок из mapping."""
    cfg = project_config_from_mapping(
        {
            "project_id": "p",
            "workflows": {"a": {"path": "1.yaml"}},
        },
    )
    loaded = LoadedProject(root=Path("."), config_path=Path("project.yaml"), config=cfg)
    reg = ProjectRegistries(loaded)
    assert reg.list_workflows() == (WorkflowRef("a", "1.yaml"),)
