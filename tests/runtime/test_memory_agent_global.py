from __future__ import annotations

from pathlib import Path

from agent_core.runtime.memory_journal import MemoryJournalStore
from agent_core.runtime.models import RuntimeIdentity, make_request_envelope
from agent_core.runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def _request(*, chat_id: str, path: str) -> object:
    identity = RuntimeIdentity(
        runtime_id="rt",
        chat_id=chat_id,
        broker_id=f"broker-{chat_id}",
        trace_id=f"trace-{chat_id}",
        goal_id="goal",
        namespace="ns",
    )
    return make_request_envelope(
        identity=identity,
        message_id=f"msg-{chat_id}",
        parent_message_id=None,
        from_agent=f"AgentWork:{chat_id}",
        to_agent="AgentMemory:global",
        msg_type="service.request",
        payload={
            "service": "memory.query_context",
            "request_id": f"req-{chat_id}",
            "path": path,
            "goal": "inspect path",
            "workspace_projects": [{"project_id": "p1", "namespace": "ns"}],
        },
    )


def test_agent_memory_global_contract_writes_per_chat_journal(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "memory-journal.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(journal_path))
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="global",
            broker_id="broker-shared",
            namespace="ns",
        ),
    )

    out_a = worker.handle(_request(chat_id="chat-a", path="a.py"))
    out_b = worker.handle(_request(chat_id="chat-b", path="b.py"))

    for out in (out_a, out_b):
        assert out["ok"] is True
        payload = out["payload"]
        assert isinstance(payload, dict)
        assert payload["project_refs"]
        assert payload["partial"] is False
        assert payload["decision_summary"]
        assert payload["recommended_next_step"]

    store = MemoryJournalStore(journal_path)
    rows_a = list(store.filter_rows(chat_id="chat-a"))
    rows_b = list(store.filter_rows(chat_id="chat-b"))
    assert [r.event_name for r in rows_a] == [
        "memory.request.received",
        "memory.slice.returned",
    ]
    assert [r.event_name for r in rows_b] == [
        "memory.request.received",
        "memory.slice.returned",
    ]
