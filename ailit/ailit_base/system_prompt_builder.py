"""Сборка эффективных system-сообщений (DP-4.2).

Приоритеты вдохновлены референсом claude-code `buildEffectiveSystemPrompt`:
- override: заменяет все остальные
- coordinator: при активном режиме координатора (в ailit пока stub)
- agent: инструкции агента (для teammate / роли)
- custom: явный system prompt из CLI (если появится)
- default: базовый system prompt приложения
- append: всегда в конце (если override не задан)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ailit_base.models import ChatMessage, MessageRole


@dataclass(frozen=True, slots=True)
class SystemPromptLayers:
    """Слои, из которых строится эффективный system prompt."""

    default: tuple[str, ...]
    append: tuple[str, ...] = ()
    custom: tuple[str, ...] = ()
    agent: tuple[str, ...] = ()
    coordinator: tuple[str, ...] = ()
    override: tuple[str, ...] = ()


def build_effective_system_messages(
    layers: SystemPromptLayers,
) -> list[ChatMessage]:
    """Построить итоговый список system-сообщений в правильном порядке."""
    if layers.override:
        return [
            ChatMessage(role=MessageRole.SYSTEM, content=s)
            for s in layers.override
        ]

    out: list[str] = []
    if layers.coordinator:
        out.extend(layers.coordinator)
    if layers.agent:
        out.extend(layers.agent)
    elif layers.custom:
        out.extend(layers.custom)
    else:
        out.extend(layers.default)
    out.extend(layers.append)
    return [ChatMessage(role=MessageRole.SYSTEM, content=s) for s in out]


def dedupe_system_texts(texts: Iterable[str]) -> tuple[str, ...]:
    """Убрать точные дубликаты, сохранив порядок первого появления."""
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return tuple(out)
