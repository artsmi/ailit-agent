from __future__ import annotations

import json

import pytest

from ailit_runtime.errors import RuntimeProtocolError
from ailit_runtime.models import (
    CONTRACT_VERSION,
    MemoryGrant,
    RuntimeIdentity,
    RuntimeRequestEnvelope,
    make_request_envelope,
)


def test_request_envelope_roundtrip_json_line() -> None:
    ident = RuntimeIdentity(
        runtime_id="r1",
        chat_id="c1",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns",
    )
    env = make_request_envelope(
        identity=ident,
        message_id="m1",
        parent_message_id=None,
        from_agent="AgentWork:c1",
        to_agent="AgentMemory:c1",
        msg_type="service.request",
        payload={"service": "memory.query_context", "request_id": "req-1"},
    )
    line = env.to_json_line()
    decoded = RuntimeRequestEnvelope.from_json_line(line)
    assert decoded.contract_version == CONTRACT_VERSION
    assert decoded.chat_id == "c1"
    assert decoded.payload["service"] == "memory.query_context"


def test_request_envelope_rejects_wrong_contract() -> None:
    raw = {
        "contract_version": "wrong",
        "runtime_id": "r1",
        "chat_id": "c1",
        "broker_id": "b1",
        "trace_id": "t1",
        "message_id": "m1",
        "parent_message_id": None,
        "goal_id": "g1",
        "namespace": "ns",
        "from_agent": "a",
        "to_agent": None,
        "created_at": "2026-04-25T00:00:00Z",
        "type": "service.request",
        "payload": {},
    }
    with pytest.raises(RuntimeProtocolError) as e:
        RuntimeRequestEnvelope.from_dict(raw)
    assert e.value.code == "contract_version_mismatch"


def test_memory_grant_from_dict() -> None:
    raw = {
        "grant_id": "gr-1",
        "issued_by": "AgentMemory:c1",
        "issued_to": "AgentWork:c1",
        "namespace": "ns",
        "path": "ailit/ailit_cli/cli.py",
        "ranges": [{"start_line": 1, "end_line": 10}],
        "whole_file": False,
        "reason": "entrypoint shortlist",
        "expires_at": "2026-04-25T01:00:00Z",
    }
    g = MemoryGrant.from_dict(raw)
    assert g.path.endswith("cli.py")
    assert g.ranges[0].start_line == 1
    assert json.loads(json.dumps(g.to_dict()))["grant_id"] == "gr-1"
