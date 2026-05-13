from __future__ import annotations

from pathlib import Path

from agent_memory.memory_journal import MemoryJournalStore
from ailit_runtime.models import RuntimeIdentity, make_request_envelope
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def _request(
    *,
    chat_id: str,
    path: str,
    project_root: Path | None = None,
) -> object:
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
            "project_root": (
                str(project_root) if project_root is not None else ""
            ),
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

    out_a = worker.handle(
        _request(chat_id="chat-a", path="a.py", project_root=tmp_path),
    )
    out_b = worker.handle(
        _request(chat_id="chat-b", path="b.py", project_root=tmp_path),
    )

    for out in (out_a, out_b):
        assert out["ok"] is True
        payload = out["payload"]
        assert isinstance(payload, dict)
        assert payload["project_refs"]
        assert isinstance(payload.get("partial"), bool)
        assert payload["decision_summary"]
        assert payload["recommended_next_step"]

    store = MemoryJournalStore(journal_path)
    rows_a = list(store.filter_rows(chat_id="chat-a"))
    rows_b = list(store.filter_rows(chat_id="chat-b"))
    assert [r.event_name for r in rows_a][0] == "memory.request.received"
    assert "memory.slice.returned" in [r.event_name for r in rows_a]
    assert [r.event_name for r in rows_b][0] == "memory.request.received"
    assert "memory.slice.returned" in [r.event_name for r in rows_b]


def test_agent_memory_query_updates_pag_without_full_repo(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    am_cfg = tmp_path / "agent_memory_quiet_llm.yaml"
    am_cfg.write_text(
        'schema_version: "1"\n'
        "memory:\n"
        "  llm:\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    journal_path = tmp_path / "memory-journal.jsonl"
    db_path = tmp_path / "pag.sqlite3"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(journal_path))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db_path))
    (tmp_path / "target.py").write_text(
        "def selected() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text(
        "def skipped() -> int:\n    return 2\n",
        encoding="utf-8",
    )
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="global",
            broker_id="broker-shared",
            namespace="ns",
        ),
    )

    out = worker.handle(
        _request(
            chat_id="chat-a",
            path="target.py",
            project_root=tmp_path,
        ),
    )

    assert out["ok"] is True
    rows = list(MemoryJournalStore(journal_path).filter_rows(chat_id="chat-a"))
    assert any(r.event_name == "memory.index.node_updated" for r in rows)
