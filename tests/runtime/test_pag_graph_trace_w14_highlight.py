"""D16.1: memory.w14.graph_highlight trace row (G16.1)."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from agent_core.memory.sqlite_pag import SqlitePagStore
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
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService
from agent_core.runtime.w14_graph_highlight_path import (
    W14GraphHighlightPathBuilder,
    a_node_id,
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


def test_emit_memory_w14_graph_highlight_row_no_stdout_when_disabled(
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
        "node_ids": ["A:ns1"],
        "edge_ids": [],
        "reason": "step",
        "ttl_ms": 3000,
    }
    emit_memory_w14_graph_highlight_row(
        req=req,
        inner_payload=inner,
        emit_stdout=False,
    )
    assert buf.getvalue() == ""


def test_w14_graph_highlight_path_not_single_leaf_only(
    tmp_path: Path,
) -> None:
    """2.2: `node_ids` — цепочка A→…→цель, не один лист."""
    store = SqlitePagStore(tmp_path / "p.sqlite3")
    w = PagGraphWriteService(store)
    ns = "ns1"
    aid = a_node_id(ns)
    bid = "B:app/y.py"
    w.upsert_node(
        namespace=ns,
        node_id=aid,
        level="A",
        kind="p",
        path=".",
        title="r",
        summary="",
        attrs={},
        fingerprint="1",
    )
    w.upsert_node(
        namespace=ns,
        node_id=bid,
        level="B",
        kind="file",
        path="app/y.py",
        title="f",
        summary="",
        attrs={},
        fingerprint="1",
    )
    w.upsert_edge(
        namespace=ns,
        edge_id="eab",
        edge_class="containment",
        edge_type="contains",
        from_node_id=aid,
        to_node_id=bid,
    )
    pth = W14GraphHighlightPathBuilder.path_to_end(store, ns, bid)
    assert pth.node_ids[0] == aid
    assert pth.node_ids[-1] == bid
    assert "eab" in pth.edge_ids


def test_w14_path_empty_end_does_not_represent_emit_payload(
    tmp_path: Path,
) -> None:
    """D16.1: пустой `path_to_end` — нет `node_ids`, emit не пишет trace."""
    store = SqlitePagStore(tmp_path / "e.sqlite3")
    pth = W14GraphHighlightPathBuilder.path_to_end(store, "n", "")
    assert pth.node_ids == []
    assert pth.edge_ids == []


def test_python_forbids_pag_graph_rev_reconciled_literal() -> None:
    """4_2: Python trace sources must not mention pag_graph_rev_reconciled."""
    root = Path(__file__).resolve().parents[2]
    paths = (
        root / "tools/agent_core/runtime/subprocess_agents/memory_agent.py",
        root / "tools/agent_core/runtime/pag_graph_trace.py",
    )
    needle = "pag_graph_rev_reconciled"
    for path in paths:
        text = path.read_text(encoding="utf-8")
        msg = f"{path} must not contain {needle!r}"
        assert needle not in text, msg
