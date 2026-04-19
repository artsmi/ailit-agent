"""Типы сессии TUI без зависимости от менеджера контекстов."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TuiSessionState:
    """Срез для ``SessionRunner`` (провайдер + активный контекст)."""

    project_root: Path
    provider: str
    model: str
    max_turns: int
    agent_id: str = "default"
    workflow_ref: str | None = None
