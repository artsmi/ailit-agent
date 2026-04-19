"""Фикстуры e2e: рабочие каталоги только внутри .ailit (gitignore)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from mini_app_factory import MiniAppMaterializer


@pytest.fixture
def e2e_workspace() -> Iterator[Path]:
    """Уникальный каталог под .ailit/e2e-workspaces для одного теста."""
    repo = Path(__file__).resolve().parents[2]
    root = repo / ".ailit" / "e2e-workspaces" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def mini_app_root(e2e_workspace: Path) -> Path:
    """Сгенерированное мини-приложение внутри e2e_workspace."""
    app = e2e_workspace / "app"
    MiniAppMaterializer().write(app)
    return app
