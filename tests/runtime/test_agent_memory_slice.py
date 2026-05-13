from __future__ import annotations

from ailit_runtime.models import CONTRACT_VERSION, RuntimeIdentity
from ailit_runtime.models import make_request_envelope
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def _request(payload: dict[str, object]) -> object:
    identity = RuntimeIdentity(
        runtime_id="rt-1",
        chat_id="chat-a",
        broker_id="broker-chat-a",
        trace_id="trace-1",
        goal_id="goal-1",
        namespace="ns",
    )
    return make_request_envelope(
        identity=identity,
        message_id="msg-1",
        parent_message_id=None,
        from_agent="AgentWork:chat-a",
        to_agent="AgentMemory:chat-a",
        msg_type="service.request",
        payload=payload,
    )


def test_memory_query_context_returns_slice_and_legacy_grant() -> None:
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="chat-a",
            broker_id="broker-chat-a",
            namespace="ns",
        ),
    )

    out = worker.handle(
        _request(
            {
                "service": "memory.query_context",
                "path": "ailit/ailit_cli/cli.py",
                "goal": "найди cli entrypoint",
                "level": "B",
            },
        ),
    )

    assert out["contract_version"] == CONTRACT_VERSION
    assert out["ok"] is True
    payload = out["payload"]
    assert isinstance(payload, dict)
    memory_slice = payload["memory_slice"]
    assert isinstance(memory_slice, dict)
    assert memory_slice["kind"] == "memory_slice"
    assert memory_slice["level"] == "B"
    assert "B:ailit/ailit_cli/cli.py" in memory_slice["node_ids"]
    assert memory_slice["estimated_tokens"] > 0
    assert payload["grants"]


def test_memory_query_context_degrades_to_project_slice_without_path() -> None:
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="chat-a",
            broker_id="broker-chat-a",
            namespace="ns",
        ),
    )

    out = worker.handle(
        _request(
            {
                "service": "memory.query_context",
                "goal": "объясни runtime",
                "level": "B",
            },
        ),
    )

    assert out["ok"] is True
    payload = out["payload"]
    assert isinstance(payload, dict)
    memory_slice = payload["memory_slice"]
    assert isinstance(memory_slice, dict)
    assert memory_slice["node_ids"] == ["A:ns"]
    assert memory_slice["injected_text"]
    assert payload["grants"] == []
