"""Эмит PAG-дельт в durable trace (G12.1, topic.publish)."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Mapping, TYPE_CHECKING

from agent_core.runtime.models import (
    RuntimeIdentity,
    RuntimeRequestEnvelope,
    TopicEvent,
    make_request_envelope,
)

if TYPE_CHECKING:
    from agent_core.runtime.compact_observability_sink import (
        CompactObservabilitySink,
    )


def _emit_memory_pag_graph_compact(
    *,
    event_name: str,
    inner_payload: Mapping[str, Any],
    compact_sink: CompactObservabilitySink,
) -> None:
    """Одна минимальная строка ``memory.pag_graph`` в ``compact.log``."""
    rev_v = inner_payload.get("rev", 0)
    try:
        rev = int(rev_v)
    except (TypeError, ValueError):
        rev = 0
    ns_raw = str(inner_payload.get("namespace", "") or "").strip()
    ns: str | None = ns_raw or None
    en = str(event_name or "").strip()

    if en == "pag.node.upsert":
        node = inner_payload.get("node")
        subject: str | None = None
        if isinstance(node, dict):
            path = str(node.get("path", "") or "").strip()
            level = str(node.get("level", "") or "").strip()
            nid = str(node.get("node_id", "") or "").strip()
            if path or level or nid:
                subject = f"{path}#{level}:{nid}"
        compact_sink.emit_memory_pag_graph(
            op="node",
            rev=rev,
            namespace=ns,
            subject=subject,
        )
        return

    if en != "pag.edge.upsert":
        return
    raw_edges = inner_payload.get("edges")
    if not isinstance(raw_edges, list) or not raw_edges:
        return
    dict_edges = [e for e in raw_edges if isinstance(e, dict)]
    if not dict_edges:
        return
    if len(dict_edges) == 1:
        e = dict_edges[0]
        eid = str(e.get("edge_id", "") or "").strip()
        ec = str(e.get("edge_class", "") or "").strip()
        et = str(e.get("edge_type", "") or "").strip()
        fr = str(e.get("from_node_id", "") or "").strip()
        to = str(e.get("to_node_id", "") or "").strip()
        subj = f"{eid}:{ec}:{et}:{fr}->{to}"
        compact_sink.emit_memory_pag_graph(
            op="edge",
            rev=rev,
            namespace=ns,
            subject=subj,
        )
        return
    first_e = str(dict_edges[0].get("edge_id", "") or "").strip()
    last_e = str(dict_edges[-1].get("edge_id", "") or "").strip()
    compact_sink.emit_memory_pag_graph(
        op="edge_batch",
        rev=rev,
        namespace=ns,
        count=len(dict_edges),
        first=first_e or None,
        last=last_e or None,
    )


def emit_pag_graph_trace_row(
    *,
    req: RuntimeRequestEnvelope,
    event_name: str,
    inner_payload: Mapping[str, Any],
    request_id: str = "",
    compact_sink: CompactObservabilitySink | None = None,
    emit_stdout: bool = True,
) -> None:
    """Пишет одну строку JSON (request envelope) в stdout для broker trace."""
    identity = RuntimeIdentity(
        runtime_id=req.runtime_id,
        chat_id=req.chat_id,
        broker_id=req.broker_id,
        trace_id=req.trace_id,
        goal_id=req.goal_id,
        namespace=req.namespace,
    )
    topic = TopicEvent(
        topic="chat",
        event_name=str(event_name),
        payload=inner_payload,
    )
    env = make_request_envelope(
        identity=identity,
        message_id=f"pag-{uuid.uuid4()}",
        parent_message_id=req.message_id,
        from_agent=f"AgentMemory:{req.chat_id}",
        to_agent=None,
        msg_type="topic.publish",
        payload=topic.to_payload(),
    )
    line = json.dumps(
        env.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if emit_stdout:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    if compact_sink is not None and str(event_name) in (
        "pag.node.upsert",
        "pag.edge.upsert",
    ):
        _emit_memory_pag_graph_compact(
            event_name=str(event_name),
            inner_payload=inner_payload,
            compact_sink=compact_sink,
        )


MEMORY_W14_GRAPH_HIGHLIGHT_EVENT: str = "memory.w14.graph_highlight"
MEMORY_W14_GRAPH_HIGHLIGHT_SCHEMA: str = "ailit_memory_w14_graph_highlight_v1"


def emit_memory_w14_graph_highlight_row(
    *,
    req: RuntimeRequestEnvelope,
    inner_payload: Mapping[str, Any],
    request_id: str = "",
    compact_sink: CompactObservabilitySink | None = None,
    emit_stdout: bool = True,
) -> None:
    """
    D16.1: W14 graph highlight (merged node_ids) — durable trace, agent Memory.

    inner_payload: schema + namespace, query_id, w14_command, w14_command_id,
    node_ids, edge_ids, reason; optional ttl_ms.
    """
    identity = RuntimeIdentity(
        runtime_id=req.runtime_id,
        chat_id=req.chat_id,
        broker_id=req.broker_id,
        trace_id=req.trace_id,
        goal_id=req.goal_id,
        namespace=req.namespace,
    )
    topic = TopicEvent(
        topic="chat",
        event_name=MEMORY_W14_GRAPH_HIGHLIGHT_EVENT,
        payload=dict(inner_payload),
    )
    env = make_request_envelope(
        identity=identity,
        message_id=f"w14gh-{uuid.uuid4()}",
        parent_message_id=req.message_id,
        from_agent=f"AgentMemory:{req.chat_id}",
        to_agent=None,
        msg_type="topic.publish",
        payload=topic.to_payload(),
    )
    line = json.dumps(
        env.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if emit_stdout:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    if compact_sink is not None:
        pl = dict(inner_payload)
        qid = str(pl.get("query_id", "") or "").strip()
        w14c = str(pl.get("w14_command", "") or "").strip()
        n_node = pl.get("node_ids")
        n_node_ct = len(n_node) if isinstance(n_node, list) else 0
        n_edge = pl.get("edge_ids")
        n_edge_ct = len(n_edge) if isinstance(n_edge, list) else 0
        compact_sink.emit_memory_w14_graph_highlight_compact(
            query_id=qid,
            w14_command=w14c,
            n_node=n_node_ct,
            n_edge=n_edge_ct,
        )
