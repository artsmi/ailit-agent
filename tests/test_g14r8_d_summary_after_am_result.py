"""
G14R.8: D summary после AM result (finish_decision).

План: plan/14-agent-memory-runtime.md §G14R.8, A14R.6, C14R.2 D.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_memory.sqlite_pag import SqlitePagStore
from agent_memory.agent_memory_query_pipeline import (
    AgentMemoryQueryPipeline,
    AgentMemoryQueryPipelineResult,
)
from agent_memory.d_creation_policy import (
    am_result_digest_goal_text,
    linked_abc_from_am_explicit_results,
)
from ailit_runtime.models import (
    RuntimeIdentity,
    make_request_envelope,
)
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


@pytest.fixture
def _runtime_identity() -> RuntimeIdentity:
    return RuntimeIdentity(
        runtime_id="rt-g14r8",
        chat_id="c-g14r8",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns-g14r8",
    )


def _w14_memory_slice() -> dict[str, object]:
    return {
        "kind": "memory_slice",
        "schema": "memory.slice.v1",
        "level": "B",
        "node_ids": ["C:src/hi.py:fn:main"],
        "edge_ids": [],
        "injected_text": "",
        "estimated_tokens": 0,
        "staleness": "w14_finish_assembly",
        "reason": "w14_finish_decision",
        "target_file_paths": ["src/hi.py"],
        "partial": False,
    }


def test_d_summary_created_after_finish_decision(
    _runtime_identity: RuntimeIdentity,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D создаётся после W14 finish_decision, не по pag_runtime_slice-only."""
    db = tmp_path / "pag.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    exp = [
        {
            "kind": "c_summary",
            "path": "src/hi.py",
            "c_node_id": "C:src/hi.py:fn:main",
            "summary": "s",
            "read_lines": [],
            "reason": "r",
        },
    ]

    def _fake_run(
        self: AgentMemoryQueryPipeline,
        *,
        memory_init: bool = False,
        **kwargs: object,
    ) -> AgentMemoryQueryPipelineResult:
        return AgentMemoryQueryPipelineResult(
            memory_slice=_w14_memory_slice(),
            partial=False,
            decision_summary="fin",
            recommended_next_step="",
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
            am_v1_explicit_results=exp,
            am_v1_status="complete",
        )

    monkeypatch.setattr(AgentMemoryQueryPipeline, "run", _fake_run)
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r8",
            broker_id="b1",
            namespace="ns-g14r8",
        ),
    )
    req = make_request_envelope(
        identity=_runtime_identity,
        message_id="m1",
        parent_message_id=None,
        from_agent="t",
        to_agent=None,
        msg_type="service.request",
        payload={
            "service": "memory.query_context",
            "request_id": "r-d",
            "goal": "подцель g14r8",
            "project_root": str(tmp_path / "p"),
            "query_id": "mem-d-1",
        },
    )
    out = w.handle(req)
    assert out.get("ok") is True
    pl = out.get("payload")
    assert isinstance(pl, dict)
    msl: object = pl.get("memory_slice")
    assert isinstance(msl, dict)
    dcr: object = msl.get("d_creation")
    assert isinstance(dcr, dict)
    assert dcr.get("gate") in ("created", "reused")
    nids: object = msl.get("node_ids")
    assert isinstance(nids, list)
    assert any(str(x).startswith("D:query_digest:") for x in nids)
    store = SqlitePagStore(db)
    found_d = None
    for n in nids:
        s = str(n)
        if s.startswith("D:query_digest:"):
            found_d = store.fetch_node(namespace="ns-g14r8", node_id=s)
            break
    assert found_d is not None
    assert str(found_d.level or "") == "D"


def test_d_summary_links_to_selected_abc_nodes(
    tmp_path: Path,
) -> None:
    """D→provenance: C и B из explicit results; A добавляет DCreationPolicy."""
    rows = [
        {
            "kind": "c_summary",
            "path": "a.py",
            "c_node_id": "C:a.py:x",
            "summary": "s",
            "read_lines": [],
            "reason": "r",
        },
        {
            "kind": "b_path",
            "path": "dir/sub",
            "c_node_id": None,
            "summary": None,
            "read_lines": [],
            "reason": "place",
        },
    ]
    got = linked_abc_from_am_explicit_results(rows)
    assert "C:a.py:x" in got
    assert "B:dir/sub" in got
    dig = am_result_digest_goal_text(
        subgoal="sg",
        decision_summary="ds",
        query_id="q-9",
    )
    assert "sg" in dig and "ds" in dig and "qid:q-9" in dig


def test_d_summary_not_used_as_b_or_c_source() -> None:
    """D-ноды не попадают в linked и не идут в B/C child refs."""
    assert linked_abc_from_am_explicit_results(
        [
            {
                "kind": "c_summary",
                "path": "x",
                "c_node_id": "D:query_digest:bad",
                "summary": "",
                "read_lines": [],
                "reason": "",
            },
        ],
    ) == []
