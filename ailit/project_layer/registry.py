"""Реестры workflow и агентов проекта."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from project_layer.loader import LoadedProject
from project_layer.models import AgentPreset, WorkflowRef


@dataclass(frozen=True, slots=True)
class ProjectRegistries:
    """Индексы по LoadedProject."""

    loaded: LoadedProject

    def workflow_path(self, workflow_key: str) -> Path:
        """Разрешить id workflow или путь к YAML."""
        key = workflow_key.strip()
        if key.endswith((".yaml", ".yml")):
            raw = Path(key)
            p = raw.resolve() if raw.is_absolute() else (self.loaded.root / key).resolve()
            if not p.is_file():
                msg = f"workflow file not found: {p}"
                raise FileNotFoundError(msg)
            return p
        ref = self.loaded.config.workflows.get(key)
        if ref is None:
            msg = f"unknown workflow id: {key!r}"
            raise KeyError(msg)
        p = (self.loaded.root / ref.path).resolve()
        if not p.is_file():
            msg = f"workflow file not found for id {key!r}: {p}"
            raise FileNotFoundError(msg)
        return p

    def agent(self, agent_id: str) -> AgentPreset:
        """Вернуть пресет агента или дефолтный пустой."""
        hit = self.loaded.config.agents.get(agent_id)
        if hit is not None:
            return hit
        if agent_id != "default":
            return self.agent("default")
        return AgentPreset(agent_id="default")

    def list_workflows(self) -> tuple[WorkflowRef, ...]:
        """Все зарегистрированные workflow."""
        return tuple(self.loaded.config.workflows.values())
