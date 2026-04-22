"""MemoryLayer (M3-2)."""

from __future__ import annotations

from agent_core.memory.layers import MemoryLayer, parse_memory_layer


def test_parse_memory_layer() -> None:
    assert parse_memory_layer(" semantic ") is MemoryLayer.SEMANTIC
    assert parse_memory_layer("nope") is None
    assert parse_memory_layer(None) is None
