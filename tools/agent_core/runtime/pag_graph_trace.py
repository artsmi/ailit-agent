"""Эмит PAG-дельт в durable trace (G12.1, topic.publish)."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Mapping, TYPE_CHECKING

from agent_core.runtime.agent_memory_external_events import (
    map_stdout_internal_to_compact_event,
)
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


def emit_pag_graph_trace_row(
    *,
    req: RuntimeRequestEnvelope,
    event_name: str,
    inner_payload: Mapping[str, Any],
    request_id: str = "",
    compact_sink: CompactObservabilitySink | None = None,
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
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    if (
        compact_sink is not None
        and str(event_name) == "pag.node.upsert"
    ):
        rid = str(request_id or "").strip()
        fields: dict[str, str | int | bool] = {"op": "node"}
        if rid:
            fields["request_id"] = rid
        ns = str(inner_payload.get("namespace", "") or "").strip()
        if ns:
            fields["namespace"] = ns
        rev_v = inner_payload.get("rev", 0)
        try:
            fields["rev"] = int(rev_v)
        except (TypeError, ValueError):
            fields["rev"] = 0
        compact_sink.emit(
            req=req,
            chat_id=req.chat_id,
            event=map_stdout_internal_to_compact_event("pag.node.upsert"),
            fields=fields,
        )


MEMORY_W14_GRAPH_HIGHLIGHT_EVENT: str = "memory.w14.graph_highlight"
MEMORY_W14_GRAPH_HIGHLIGHT_SCHEMA: str = "ailit_memory_w14_graph_highlight_v1"


def emit_memory_w14_graph_highlight_row(
    *,
    req: RuntimeRequestEnvelope,
    inner_payload: Mapping[str, Any],
    request_id: str = "",
    compact_sink: CompactObservabilitySink | None = None,
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
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    if compact_sink is not None:
        pl = dict(inner_payload)
        rid = str(request_id or "").strip()
        fields: dict[str, str | int | bool] = {}
        if rid:
            fields["request_id"] = rid
        qid = str(pl.get("query_id", "") or "").strip()
        if qid:
            fields["query_id"] = qid
        w14c = str(pl.get("w14_command", "") or "").strip()
        if w14c:
            fields["w14_command"] = w14c
        n_node = pl.get("node_ids")
        if isinstance(n_node, list):
            fields["n_node"] = len(n_node)
        n_edge = pl.get("edge_ids")
        if isinstance(n_edge, list):
            fields["n_edge"] = len(n_edge)
        compact_sink.emit(
            req=req,
            chat_id=req.chat_id,
            event=map_stdout_internal_to_compact_event(
                MEMORY_W14_GRAPH_HIGHLIGHT_EVENT,
            ),
            fields=fields,
        )
