"""Политика разрешений с учётом perm-режима и аргументов вызова."""

from __future__ import annotations

import json
from typing import Any

from agent_work.session.perm_tool_mode import (
    PermToolMode,
    normalize_perm_tool_mode,
    read_plan_write_file_allowed,
)
from agent_work.tool_runtime.multi_root_paths import (
    resolve_absolute_file_under_work_roots,
)
from agent_work.tool_runtime.executor import ToolInvocation
from agent_work.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_work.tool_runtime.spec import SideEffectClass, ToolSpec


class ModePermissionPolicy:
    """Режим → allow/ask/deny поверх базового PermissionEngine."""

    def __init__(
        self,
        mode: str,
        *,
        base: PermissionEngine | None = None,
        edit_write_default: PermissionDecision = PermissionDecision.ALLOW,
        edit_shell_default: PermissionDecision = PermissionDecision.ALLOW,
    ) -> None:
        """Инициализировать политику для канонического режима."""
        self._mode = normalize_perm_tool_mode(mode)
        self._base_read = PermissionEngine(
            write_default=PermissionDecision.DENY,
            shell_default=PermissionDecision.DENY,
            network_default=PermissionDecision.ASK,
        )
        self._base_edit = base or PermissionEngine(
            write_default=edit_write_default,
            shell_default=edit_shell_default,
            network_default=PermissionDecision.ASK,
        )

    @property
    def mode(self) -> str:
        """Текущий нормализованный режим."""
        return self._mode

    def evaluate(
        self,
        spec: ToolSpec,
        inv: ToolInvocation | None = None,
    ) -> PermissionDecision:
        """Оценить вызов с учётом режима и аргументов (shell/write)."""
        m = self._mode
        if m == PermToolMode.EDIT.value:
            return self._base_edit.evaluate(spec, inv)

        if spec.name in ("run_shell", "run_shell_session"):
            if m != PermToolMode.EXPLORE.value:
                return PermissionDecision.DENY
            return PermissionDecision.ALLOW

        if spec.name in ("write_file", "apply_patch"):
            if m in (PermToolMode.READ.value, PermToolMode.EXPLORE.value):
                return PermissionDecision.DENY
            if m == PermToolMode.READ_PLAN.value:
                rel = (
                    _write_path_from_inv(inv)
                    if spec.name == "write_file"
                    else _apply_patch_relative_path_from_inv(inv)
                )
                if rel and read_plan_write_file_allowed(rel):
                    return PermissionDecision.ALLOW
                return PermissionDecision.ASK
            return PermissionDecision.DENY

        if spec.side_effect is SideEffectClass.WRITE:
            if spec.name == "kb_write_fact":
                return PermissionDecision.ALLOW
            if spec.name.startswith("kb_"):
                return PermissionDecision.ASK
            return PermissionDecision.DENY

        return self._base_read.evaluate(spec, inv)


def _shell_command_from_inv(inv: ToolInvocation | None) -> str:
    if inv is None:
        return ""
    try:
        raw: dict[str, Any] = json.loads(inv.arguments_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("command") or "").strip()


def _write_path_from_inv(inv: ToolInvocation | None) -> str:
    if inv is None:
        return ""
    try:
        raw: dict[str, Any] = json.loads(inv.arguments_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("path") or "").strip()


def _apply_patch_relative_path_from_inv(inv: ToolInvocation | None) -> str:
    if inv is None:
        return ""
    try:
        raw: dict[str, Any] = json.loads(inv.arguments_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(raw, dict):
        return ""
    fp = str(raw.get("filePath") or "").strip()
    if not fp:
        return ""
    try:
        _, rel = resolve_absolute_file_under_work_roots(fp)
    except (OSError, TypeError, ValueError):
        return ""
    return rel


def build_mode_permission_policy(
    mode: str,
    *,
    legacy_engine: PermissionEngine | None = None,
) -> ModePermissionPolicy | PermissionEngine:
    """Политика: edit → legacy engine, иначе ModePermissionPolicy."""
    m = normalize_perm_tool_mode(mode)
    if m == PermToolMode.EDIT.value:
        return legacy_engine or PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        )
    return ModePermissionPolicy(m, base=legacy_engine)
