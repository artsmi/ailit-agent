"""Состояние сессии агента."""

from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    """Жизненный цикл session loop."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    FINISHED = "finished"
    BUDGET_EXCEEDED = "budget_exceeded"
    ERROR = "error"
