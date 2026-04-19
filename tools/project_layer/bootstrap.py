"""Сборка augmentation для workflow и настроек чата без импорта session loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from project_layer.knowledge import (
    ContextSnapshot,
    FilesystemKnowledgeRefresh,
    KnowledgeRefreshPort,
    StubKnowledgeRefresh,
)
from project_layer.loader import LoadedProject
from project_layer.plugin_skills import collect_plugin_skill_snippets
from project_layer.registry import ProjectRegistries
from project_layer.teammate_prompt import TEAMMATE_MAILBOX_SYSTEM_ADDENDUM


@dataclass(frozen=True, slots=True)
class WorkflowAugmentation:
    """Доп. system-сообщения и shortlist для WorkflowRunConfig."""

    extra_system_messages: tuple[str, ...]
    shortlist_keywords: frozenset[str] | None
    temperature: float


@dataclass(frozen=True, slots=True)
class ChatSessionTuning:
    """Параметры чата, вычисленные из проекта."""

    extra_system_messages: tuple[str, ...]
    shortlist_keywords: frozenset[str] | None
    temperature: float | None
    max_turns: int | None


def _rules_text(loaded: LoadedProject) -> str | None:
    rel = loaded.config.paths.rules
    if not rel:
        return None
    path = (loaded.root / rel).resolve()
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _knowledge_port_for(loaded: LoadedProject) -> KnowledgeRefreshPort:
    mode = loaded.config.context.knowledge_refresh.mode
    if mode == "stub":
        return StubKnowledgeRefresh()
    return FilesystemKnowledgeRefresh()


def compute_workflow_augmentation(
    loaded: LoadedProject,
    snapshot: ContextSnapshot | None = None,
) -> WorkflowAugmentation:
    """Построить augmentation для прогона workflow."""
    snap = snapshot or _knowledge_port_for(loaded).refresh(loaded)
    extras: list[str] = []
    rules = _rules_text(loaded)
    if rules:
        extras.append(f"Project rules:\n{rules}")
    if loaded.config.memory_hints:
        extras.append("Memory hints:\n" + "\n".join(f"- {h}" for h in loaded.config.memory_hints))
    if snap.preview_text:
        extras.append(f"Canonical context preview:\n{snap.preview_text[:8000]}")
    keys: frozenset[str] | None = (
        snap.shortlist_keywords if len(snap.shortlist_keywords) > 0 else None
    )
    return WorkflowAugmentation(
        extra_system_messages=tuple(extras),
        shortlist_keywords=keys,
        temperature=0.0,
    )


def compute_chat_tuning(
    loaded: LoadedProject,
    agent_id: str,
    snapshot: ContextSnapshot | None = None,
) -> ChatSessionTuning:
    """Параметры SessionSettings + дополнительные system-сообщения для чата."""
    reg = ProjectRegistries(loaded)
    agent = reg.agent(agent_id)
    snap = snapshot or _knowledge_port_for(loaded).refresh(loaded)
    extras: list[str] = []
    rules = _rules_text(loaded)
    if rules:
        extras.append(f"Project rules:\n{rules}")
    if loaded.config.memory_hints:
        extras.append("Memory hints:\n" + "\n".join(f"- {h}" for h in loaded.config.memory_hints))
    if (agent.role or "").lower() == "teammate":
        extras.append(TEAMMATE_MAILBOX_SYSTEM_ADDENDUM)
    if agent.system_append:
        extras.append(agent.system_append)
    plug = collect_plugin_skill_snippets(loaded)
    if plug:
        extras.append("Installed plugin skills (reference):\n" + plug)
    merged_keywords = frozenset(snap.shortlist_keywords | agent.shortlist_extra)
    keys: frozenset[str] | None = merged_keywords if merged_keywords else None
    return ChatSessionTuning(
        extra_system_messages=tuple(extras),
        shortlist_keywords=keys,
        temperature=agent.temperature,
        max_turns=agent.max_turns,
    )


def format_agent_run_command(
    *,
    project_root: Path,
    workflow_ref: str,
    provider: str,
    model: str,
    max_turns: int,
    dry_run: bool,
) -> str:
    """Строка CLI для копирования."""
    flags = f"--project-root {project_root} --provider {provider} --model {model} --max-turns {max_turns}"
    if dry_run:
        flags += " --dry-run"
    return f"ailit agent run {workflow_ref} {flags}".strip()
