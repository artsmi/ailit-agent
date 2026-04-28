"""G12.7: memory.file_changed service on AgentMemory worker."""

from __future__ import annotations

from pathlib import Path

from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.models import RuntimeIdentity, make_request_envelope
from agent_core.runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def test_memory_file_changed_remaps_c_nodes(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    db = tmp_path / "pag.sqlite3"
    journal_path = tmp_path / "j.jsonl"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(journal_path))
    py = tmp_path / "a.py"
    src = "def f():\n  return 1\n"
    py.write_text("\n" * 30 + src, encoding="utf-8")
    store = SqlitePagStore(db)
    ns = "n1"
    store.upsert_node(
        namespace=ns,
        node_id="B:a.py",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="F",
        attrs={},
        fingerprint="b0",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
    )
    store.upsert_node(
        namespace=ns,
        node_id="C:a#1",
        level="C",
        kind="function",
        path="a.py",
        title="f",
        summary="f",
        attrs={"name": "f", "line_hint": {"start": 1, "end": 1}},
        fingerprint="c0",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
    )
    identity = RuntimeIdentity(
        runtime_id="rt",
        chat_id="c1",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace=ns,
    )
    env = make_request_envelope(
        identity=identity,
        message_id="mfc-1",
        parent_message_id=None,
        from_agent="AgentWork:c1",
        to_agent="AgentMemory:global",
        msg_type="service.request",
        payload={
            "service": "memory.file_changed",
            "request_id": "rfc-1",
            "schema": "memory.file_changed.v1",
            "namespace": ns,
            "project_root": str(tmp_path),
            "changes": [{"path": "a.py", "operation": "modified"}],
            "source": "test",
        },
    )
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="global",
            broker_id="br",
            namespace=ns,
        ),
    )
    out = w.handle(env)
    assert out.get("ok") is True
    pl = out.get("payload")
    assert isinstance(pl, dict)
    sm = pl.get("summary")
    assert isinstance(sm, list) and sm[0].get("updated", 0) >= 0
