"""Слой памяти ailit: working / episodic / semantic / procedural (M3-2)."""

from __future__ import annotations

from enum import Enum


class MemoryLayer(str, Enum):
    """Канонические уровни памяти (см. plan/workflow-memory-3.md)."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


def parse_memory_layer(value: str | None) -> MemoryLayer | None:
    """Разобрать метку слоя; неизвестное — None."""
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if not s:
        return None
    for m in MemoryLayer:
        if m.value == s:
            return m
    return None
