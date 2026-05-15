"""S2: golden stdout → compact ``event=`` (failure-retry-observability.md)."""

from __future__ import annotations

from agent_memory.contracts.agent_memory_external_events import (
    AGENT_MEMORY_EXTERNAL_EVENT_V1,
    STDOUT_INTERNAL_TO_COMPACT_EVENT,
    build_external_event_v1,
    map_stdout_internal_to_compact_event,
    normalize_compact_event_name,
)


def test_stdout_to_compact_golden_mapping_table() -> None:
    assert STDOUT_INTERNAL_TO_COMPACT_EVENT == {
        "pag.node.upsert": "memory.pag_graph",
        "pag.edge.upsert": "memory.pag_graph",
        "memory.w14.graph_highlight": "memory.w14_graph_highlight",
    }
    assert (
        map_stdout_internal_to_compact_event("pag.node.upsert")
        == "memory.pag_graph"
    )
    assert (
        map_stdout_internal_to_compact_event("pag.edge.upsert")
        == "memory.pag_graph"
    )
    assert (
        map_stdout_internal_to_compact_event("memory.w14.graph_highlight")
        == "memory.w14_graph_highlight"
    )
    assert (
        normalize_compact_event_name("pag.node.upsert") == "memory.pag_graph"
    )
    assert (
        normalize_compact_event_name("memory.w14.graph_highlight")
        == "memory.w14_graph_highlight"
    )
    assert (
        normalize_compact_event_name("memory.pag_graph") == "memory.pag_graph"
    )


def test_build_external_event_v1_shape() -> None:
    ev = build_external_event_v1(
        event_type="heartbeat",
        query_id="q1",
        payload={"session_alive": True},
    )
    assert ev["schema_version"] == AGENT_MEMORY_EXTERNAL_EVENT_V1
    assert ev["event_type"] == "heartbeat"
    assert ev["query_id"] == "q1"
    assert ev["payload"] == {"session_alive": True}
    assert ev["truncated"] is False
    assert "timestamp" in ev
