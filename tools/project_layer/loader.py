"""Загрузка project.yaml с валидацией."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from project_layer.models import ProjectConfig, project_config_from_mapping


@dataclass(frozen=True, slots=True)
class LoadedProject:
    """Загруженный проект: корень + путь к yaml + модель."""

    root: Path
    config_path: Path
    config: ProjectConfig


def load_project_mapping(data: Mapping[str, Any]) -> ProjectConfig:
    """Разобрать уже загруженный mapping."""
    if not isinstance(data, Mapping):
        msg = "project root YAML must be a mapping"
        raise TypeError(msg)
    return project_config_from_mapping(data)


def load_project(config_path: Path) -> LoadedProject:
    """Загрузить project.yaml (или иной файл) и вернуть LoadedProject."""
    path = config_path.resolve()
    raw_text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text)
    if not isinstance(data, dict):
        msg = "project YAML root must be a mapping"
        raise ValueError(msg)
    cfg = load_project_mapping(data)
    root = path.parent
    return LoadedProject(root=root, config_path=path, config=cfg)


def default_project_yaml_path(project_root: Path) -> Path:
    """Путь к project.yaml по умолчанию."""
    return project_root.resolve() / "project.yaml"
