"""Режимы perm-5: наборы инструментов и вспомогательные проверки путей."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from agent_core.models import ToolDefinition
from agent_core.session.context_pager import READ_CONTEXT_PAGE_NAME
from agent_core.session.tool_bridge import tool_definitions_from_registry
from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.spec import SideEffectClass


class PermToolMode(str, Enum):
    """Канонические режимы инструментов (perm-5)."""

    READ = "read"
    READ_PLAN = "read_plan"
    EXPLORE = "explore"
    EDIT = "edit"


READ_SIDE_EFFECTS: frozenset[SideEffectClass] = frozenset(
    {
        SideEffectClass.NONE,
        SideEffectClass.READ_ONLY,
        SideEffectClass.READ,
    },
)

# Инструменты, разрешённые в read (включая KB write как в постановке).
READ_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "list_dir",
        "glob_file",
        "grep",
        "read_file",
        "read_symbol",
        READ_CONTEXT_PAGE_NAME,
        "kb_search",
        "kb_fetch",
        "kb_write_fact",
    },
)

READ_PLAN_SAFE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
    },
)

READ_PLAN_PATH_PREFIXES: tuple[str, ...] = (
    "docs/",
    ".ailit/plan/",
    "plan/",
)


@dataclass(frozen=True, slots=True)
class PermToolExposureMeta:
    """Мета применения профиля perm-режима."""

    perm_mode: str
    tools_total: int
    tools_exposed: int
    schema_chars: int
    schema_chars_full: int
    schema_savings: int


def _schema_chars(defs: tuple[ToolDefinition, ...]) -> int:
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


def normalize_perm_tool_mode(raw: str | None) -> str:
    """Нормализовать строку режима к канону или explore."""
    s = (raw or "").strip().lower()
    for m in PermToolMode:
        if m.value == s:
            return m.value
    return PermToolMode.EXPLORE.value


def read_plan_write_file_allowed(relative_path: str) -> bool:
    """True если write_file в read_plan разрешён без доп. вопросов."""
    rel = (relative_path or "").strip().replace("\\", "/")
    if not rel or rel.endswith("/"):
        return False
    low = rel.lower()
    for pref in READ_PLAN_PATH_PREFIXES:
        if low.startswith(pref):
            break
    else:
        # Вне docs/.ailit/plan/plan — только «безопасные» расширения.
        p = PurePosixPath(rel)
        suf = "".join(p.suffixes)
        if suf:
            last = suf.split(".")[-1]
            tail = f".{last}" if last else ""
        else:
            tail = ""
        if tail.lower() not in READ_PLAN_SAFE_SUFFIXES:
            return False
    p2 = PurePosixPath(rel)
    name = p2.name.lower()
    blocked_names = {
        "makefile",
        "dockerfile",
        "dockerfile.dev",
        "cmakelists.txt",
    }
    if name in blocked_names:
        return False
    for ext in (".py", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".exe"):
        if low.endswith(ext):
            return False
    return True


_EXPLORE_SHELL_ALLOWLIST = (
    re.compile(r"^\s*git\s+status(\s|$)", re.IGNORECASE),
    re.compile(r"^\s*git\s+diff(\s|$)", re.IGNORECASE),
    re.compile(r"^\s*git\s+log(\s|$)", re.IGNORECASE),
    re.compile(r"^\s*git\s+branch(\s|$)", re.IGNORECASE),
    re.compile(r"^\s*pwd\s*$", re.IGNORECASE),
    re.compile(r"^\s*ls(\s|$)", re.IGNORECASE),
    re.compile(r"^\s*echo\s+", re.IGNORECASE),
    re.compile(r"^\s*head\s+", re.IGNORECASE),
    re.compile(r"^\s*cat\s+", re.IGNORECASE),
    re.compile(r"^\s*wc\s+", re.IGNORECASE),
)


def explore_shell_command_allowed(command: str) -> bool:
    """Allowlist shell для режима explore (без ask)."""
    cmd = (command or "").strip()
    if not cmd:
        return False
    for pat in _EXPLORE_SHELL_ALLOWLIST:
        if pat.search(cmd):
            return True
    return False


def tool_names_for_perm_mode(mode: str) -> frozenset[str] | None:
    """Имена инструментов для режима; None = без фильтра (edit/legacy)."""
    m = normalize_perm_tool_mode(mode)
    if m == PermToolMode.EDIT.value:
        return None
    if m == PermToolMode.READ.value:
        return READ_TOOL_NAMES
    if m == PermToolMode.READ_PLAN.value:
        return READ_TOOL_NAMES | frozenset({"write_file"})
    if m == PermToolMode.EXPLORE.value:
        return READ_TOOL_NAMES | frozenset({"run_shell", "run_shell_session"})
    return None


def tool_definitions_for_perm_mode(
    registry: ToolRegistry,
    mode: str,
) -> tuple[tuple[ToolDefinition, ...], PermToolExposureMeta]:
    """Собрать определения инструментов под perm-режим."""
    full_tuple = tool_definitions_from_registry(registry)
    full_chars = _schema_chars(full_tuple)
    names = tool_names_for_perm_mode(mode)
    if names is None:
        meta = PermToolExposureMeta(
            perm_mode=normalize_perm_tool_mode(mode),
            tools_total=len(full_tuple),
            tools_exposed=len(full_tuple),
            schema_chars=full_chars,
            schema_chars_full=full_chars,
            schema_savings=0,
        )
        return full_tuple, meta
    full_specs = list(registry.specs.values())
    exposed_specs = [s for s in full_specs if s.name in names]
    out: list[ToolDefinition] = []
    for s in sorted(exposed_specs, key=lambda sp: sp.name):
        out.append(
            ToolDefinition(
                name=s.name,
                description=s.description,
                parameters=dict(s.parameters_schema),
            ),
        )
    exposed_tuple = tuple(out)
    exp_chars = _schema_chars(exposed_tuple)
    meta2 = PermToolExposureMeta(
        perm_mode=normalize_perm_tool_mode(mode),
        tools_total=len(full_tuple),
        tools_exposed=len(exposed_tuple),
        schema_chars=exp_chars,
        schema_chars_full=full_chars,
        schema_savings=max(0, full_chars - exp_chars),
    )
    return exposed_tuple, meta2
