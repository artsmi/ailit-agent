"""Пути относительно корня репозитория ailit-agent."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Корень репозитория (каталог с pyproject.toml)."""
    return Path(__file__).resolve().parents[2]
