"""Единый контракт описания инструмента (без привязки к модели)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class SideEffectClass(str, Enum):
    """Класс побочных эффектов для governance."""

    NONE = "none"
    READ_ONLY = "read_only"
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Метаданные инструмента для runtime, UI и политик."""

    name: str
    description: str
    parameters_schema: Mapping[str, Any]
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY
    requires_approval: bool = False
    allow_parallel: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в JSON-совместимый dict."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters_schema": dict(self.parameters_schema),
            "side_effect": self.side_effect.value,
            "requires_approval": self.requires_approval,
            "allow_parallel": self.allow_parallel,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> ToolSpec:
        """Восстановление из dict."""
        se = SideEffectClass(str(data.get("side_effect", SideEffectClass.READ_ONLY.value)))
        return ToolSpec(
            name=str(data["name"]),
            description=str(data.get("description", "")),
            parameters_schema=dict(data.get("parameters_schema", {})),
            side_effect=se,
            requires_approval=bool(data.get("requires_approval", False)),
            allow_parallel=bool(data.get("allow_parallel", False)),
            metadata=dict(data.get("metadata", {})),
        )
