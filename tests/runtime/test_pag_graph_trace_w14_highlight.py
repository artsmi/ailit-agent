"""D16.1: memory.w14.graph_highlight trace row (G16.1)."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest

from agent_core.runtime.models import (
    RuntimeRequestEnvelope,
    make_request_envelope,
    RuntimeIdentity,
)
from agent_core.runtime.pag_graph_trace import (
    MEMORY_W14_GRAPH_HIGHLIGHT_EVENT,
    MEMORY_W14_GRAPH_HIGHLIGHT_SCHEMA,
    emit_memory_w14_graph_highlight_row,
)


def _sample_req() -> RuntimeRequestEnvelope:
    ident = RuntimeIdentity(
        runtime_id="r1",
        chat_id="chat-abc",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns1",
    )
    return make_request_envelope(
        identity=ident,
        message_id="m-root",
        parent_message_id=None,
        from_agent="test",
        to_agent=None,
        msg_type="service.request",
        payload={"service": "x", "request_id": "r", "payload": {}},
    )


def test_emit_memory_w14_graph_highlight_row_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = _sample_req()
    buf = StringIO()

    def _write(s: str) -> int:
        buf.write(s)
        return len(s)

    monkeypatch.setattr("sys.stdout.write", _write)
    monkeypatch.setattr("sys.stdout.flush", lambda: None)
    inner: dict[str, Any] = {
        "schema": MEMORY_W14_GRAPH_HIGHLIGHT_SCHEMA,
        "namespace": "ns1",
        "query_id": "q1",
        "w14_command": "plan_traversal",
        "w14_command_id": "q1:pt",
        "node_ids": ["A:ns1", "B:foo.py"],
        "edge_ids": ["e:abc123"],
        "reason": "step",
        "ttl_ms": 3000,
    }
    emit_memory_w14_graph_highlight_row(req=req, inner_payload=inner)
    line = buf.getvalue().strip()
    assert line
    row = json.loads(line)
    assert row["type"] == "topic.publish" or "msg_type" in row
    # Envelope: from_agent must route to this chat
    assert "AgentMemory:chat-abc" in str(row.get("from_agent", ""))
    pl = row.get("payload", {})
    if isinstance(pl, dict) and "event_name" in pl:
        assert pl["event_name"] == MEMORY_W14_GRAPH_HIGHLIGHT_EVENT
        inner2 = pl.get("payload", {})
        assert inner2.get("schema") == MEMORY_W14_GRAPH_HIGHLIGHT_SCHEMA
        assert inner2.get("node_ids") == ["A:ns1", "B:foo.py"]
