"""Selective tool exposure: схема tool-calling (M3, см. ruflo plan)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ailit_base.models import ToolDefinition
from agent_work.session.context_pager import READ_CONTEXT_PAGE_NAME
from agent_work.session.tool_bridge import tool_definitions_from_registry
from agent_work.tool_runtime.registry import ToolRegistry
from agent_work.tool_runtime.spec import SideEffectClass


@dataclass(frozen=True, slots=True)
class ToolExposureMeta:
    """Сводка применения профиля exposure (E2E-M3-04: экономия схемы)."""

    mode: str
    tools_total: int
    tools_exposed: int
    schema_chars: int
    schema_chars_full: int
    schema_savings: int


def _schema_chars(defs: tuple[ToolDefinition, ...]) -> int:
    """Оценка размера схемы в сторону провайдера (приближённо)."""
    n = 0
    for d in defs:
        n += len(d.name) + len(d.description)
        try:
            n += len(
                json.dumps(
                    d.parameters,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        except (TypeError, ValueError):
            n += 8
    return n


def tool_definitions_exposed(
    registry: ToolRegistry,
    mode: str,
) -> tuple[ToolDefinition, ...]:
    """Отфильтровать `ToolDefinition` согласно `mode` (низкоуровневый)."""
    raw = (mode or "full").strip().lower()
    if raw in ("", "full", "all"):
        return tool_definitions_from_registry(registry)
    if raw in ("read_only", "readonly", "ro", "analyse", "analyze"):
        allowed: set[SideEffectClass] = {
            SideEffectClass.NONE,
            SideEffectClass.READ_ONLY,
            SideEffectClass.READ,
        }
        specs = [
            s
            for s in registry.specs.values()
            if s.side_effect in allowed
        ]
    elif raw in (
        "fs",
        "filesystem",
        "fs_readonly",
        "fs_readonly_only",
    ):
        names: frozenset[str] = frozenset(
            {
                "list_dir",
                "glob_file",
                "grep",
                "read_file",
                READ_CONTEXT_PAGE_NAME,
            },
        )
        specs = [s for s in registry.specs.values() if s.name in names]
    else:
        return tool_definitions_from_registry(registry)
    out: list[ToolDefinition] = []
    for s in sorted(specs, key=lambda sp: sp.name):
        out.append(
            ToolDefinition(
                name=s.name,
                description=s.description,
                parameters=dict(s.parameters_schema),
            ),
        )
    return tuple(out)


def tool_definitions_for_settings(
    registry: ToolRegistry,
    tool_exposure: str,
) -> tuple[tuple[ToolDefinition, ...], ToolExposureMeta]:
    """Собрать `ToolDefinition` + мета для диагностики/CLI."""
    full = tool_definitions_from_registry(registry)
    m = (tool_exposure or "full").strip().lower()
    exposed = tool_definitions_exposed(registry, m)
    full_chars = _schema_chars(full)
    exp_chars = _schema_chars(exposed)
    if m in ("", "full", "all") or not m:
        meta = ToolExposureMeta(
            mode="full",
            tools_total=len(full),
            tools_exposed=len(exposed),
            schema_chars=exp_chars,
            schema_chars_full=full_chars,
            schema_savings=0,
        )
        return full, meta
    meta2 = ToolExposureMeta(
        mode=m,
        tools_total=len(full),
        tools_exposed=len(exposed),
        schema_chars=exp_chars,
        schema_chars_full=full_chars,
        schema_savings=max(0, full_chars - exp_chars),
    )
    return exposed, meta2
