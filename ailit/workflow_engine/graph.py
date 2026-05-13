"""Сущности workflow graph (машинная оркестрация)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class BlockedReason(str, Enum):
    """Структурированная причина блокировки."""

    NONE = "none"
    HUMAN_GATE = "human_gate"
    BUDGET = "budget"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HumanGate:
    """Точка ожидания человека (метаданные для UI)."""

    gate_id: str
    description: str


@dataclass(frozen=True, slots=True)
class Barrier:
    """Барьер между этапами (MVP: декларативный маркер)."""

    barrier_id: str
    stage_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Transition:
    """Переход между стадиями."""

    from_stage: str
    to_stage: str
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class Task:
    """Одна задача внутри стадии."""

    task_id: str
    system_prompt: str
    user_text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Stage:
    """Стадия workflow."""

    stage_id: str
    tasks: tuple[Task, ...]
    human_gate: HumanGate | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Workflow:
    """Определение workflow."""

    workflow_id: str
    stages: tuple[Stage, ...]
    hybrid: bool = False
    policy_ref: str | None = None
    transitions: tuple[Transition, ...] = ()
    barriers: tuple[Barrier, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
