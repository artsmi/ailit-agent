"""Пути к глобальному state: ``~/.ailit`` (без каталога ``.ailit`` в репо)."""

from __future__ import annotations

import os
from pathlib import Path


def user_ailit_root(home: Path | None = None) -> Path:
    """Корень: ``$HOME/.ailit`` (при тестах задайте ``HOME``)."""
    if home is not None:
        return home.expanduser().resolve() / ".ailit"
    env = os.environ.get("HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve() / ".ailit"
    return Path.home() / ".ailit"


def user_global_config_path(home: Path | None = None) -> Path:
    """Index: active ids + schema. Файл ``~/.ailit/config.yaml``."""
    return user_ailit_root(home) / "config.yaml"


def user_projects_root(home: Path | None = None) -> Path:
    """Каталог: ``~/.ailit/projects`` — по одной папке на проект."""
    return user_ailit_root(home) / "projects"


def user_project_dir(project_id: str, home: Path | None = None) -> Path:
    """``~/.ailit/projects/<project_id>/``."""
    safe = "".join(
        c for c in (project_id or "").strip() if c.isalnum() or c in ("-", "_")
    ) or "unknown"
    return user_projects_root(home) / safe
