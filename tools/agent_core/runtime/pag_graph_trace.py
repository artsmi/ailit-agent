"""Эмит PAG-дельт в durable trace (G12.1, topic.publish)."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Mapping

from agent_core.runtime.models import (
    RuntimeIdentity,
    RuntimeRequestEnvelope,
    TopicEvent,
    make_request_envelope,
)


def emit_pag_graph_trace_row(
    *,
    req: RuntimeRequestEnvelope,
    event_name: str,
    inner_payload: Mapping[str, Any],
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
