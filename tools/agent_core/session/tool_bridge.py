"""Мост реестра инструментов → ToolDefinition для провайдера."""

from __future__ import annotations

from agent_core.models import ToolDefinition
from agent_core.tool_runtime.registry import ToolRegistry


def tool_definitions_from_registry(registry: ToolRegistry) -> tuple[ToolDefinition, ...]:
    """Построить описания tools для ChatRequest."""
    defs: list[ToolDefinition] = []
    for spec in registry.specs.values():
        defs.append(
            ToolDefinition(
                name=spec.name,
                description=spec.description,
                parameters=dict(spec.parameters_schema),
            )
        )
    return tuple(defs)
