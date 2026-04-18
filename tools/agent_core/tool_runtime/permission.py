"""Решения allow / ask / deny по классу побочного эффекта."""

from __future__ import annotations

from enum import Enum

from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec


class PermissionDecision(str, Enum):
    """Результат оценки разрешения на вызов инструмента."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionEngine:
    """Единая точка политики разрешений (не в промптах)."""

    def __init__(
        self,
        *,
        destructive_default: PermissionDecision = PermissionDecision.DENY,
        write_default: PermissionDecision = PermissionDecision.ASK,
        network_default: PermissionDecision = PermissionDecision.ASK,
    ) -> None:
        """Инициализировать политику по умолчанию для классов эффектов."""
        self._destructive_default = destructive_default
        self._write_default = write_default
        self._network_default = network_default

    def evaluate(self, spec: ToolSpec) -> PermissionDecision:
        """Оценить разрешён ли вызов до исполнения (без учёта session approvals)."""
        if spec.requires_approval:
            return PermissionDecision.ASK
        effect = spec.side_effect
        if effect in (SideEffectClass.NONE, SideEffectClass.READ_ONLY, SideEffectClass.READ):
            return PermissionDecision.ALLOW
        if effect is SideEffectClass.WRITE:
            return self._write_default
        if effect is SideEffectClass.NETWORK:
            return self._network_default
        if effect is SideEffectClass.DESTRUCTIVE:
            return self._destructive_default
        return PermissionDecision.DENY
