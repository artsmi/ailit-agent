"""G14R.0: W14 clean replacement, payload.agent_memory_result (W14 G14R.0)."""

from __future__ import annotations

import pytest

from agent_memory.agent_memory_query_pipeline import (
    AgentMemoryQueryPipeline,
    AgentMemoryQueryPipelineResult,
)
from ailit_runtime.models import (
    RuntimeIdentity,
    make_request_envelope,
)
import agent_memory.w14_clean_replacement as w14
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


@pytest.fixture
def _runtime_identity() -> RuntimeIdentity:
    return RuntimeIdentity(
        runtime_id="rt-g14r0",
        chat_id="c-g14r0",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns",
    )


def _minimal_memory_slice() -> dict[str, object]:
    return {
        "kind": "memory_slice",
        "schema": "memory.slice.v1",
        "level": "B",
        "node_ids": ["C:src/x.py:1-10"],
        "edge_ids": [],
        "injected_text": "test context for g14r0",
        "estimated_tokens": 10,
        "staleness": "fresh",
        "reason": "test_synthetic",
        "target_file_paths": ["src/x.py"],
    }


def test_w14_clean_replacement_has_no_migration_mode() -> None:
    """D14R.1: W14 — fresh store; план G14R.0 тест по имени."""
    assert w14.W14_FRESH_MEMORY_STORES_ONLY is True


def test_query_context_returns_agent_memory_result_next_to_memory_slice(
    _runtime_identity: RuntimeIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C14R.1a: agent_memory_result отдельно от memory_slice."""

    def _fake_run(
        self: AgentMemoryQueryPipeline,
        *,
        memory_init: bool = False,
        **kwargs: object,
    ) -> AgentMemoryQueryPipelineResult:
        return AgentMemoryQueryPipelineResult(
            memory_slice=_minimal_memory_slice(),
            partial=False,
            decision_summary="ok",
            recommended_next_step="",
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=False,
            llm_disabled_fallback=True,
        )

    monkeypatch.setattr(AgentMemoryQueryPipeline, "run", _fake_run)
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r0",
            broker_id="b1",
            namespace="ns",
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
            "request_id": "r1",
            "goal": "read context",
            "project_root": "/tmp",
            "query_id": "mem-test-1",
        },
    )
    out = w.handle(req)
    assert out.get("ok") is True
    pl = out.get("payload")
    assert isinstance(pl, dict)
    assert "memory_slice" in pl
    assert "agent_memory_result" in pl
    msl: object = pl.get("memory_slice")
    assert isinstance(msl, dict)
    assert "agent_memory_result" not in msl
    amr: object = pl.get("agent_memory_result")
    assert isinstance(amr, dict)
    assert amr.get("schema_version") == "agent_memory_result.v1"
    assert amr.get("query_id") == "mem-test-1"
    assert amr.get("status") in ("complete", "partial", "blocked")


def test_legacy_requested_reads_rejected_after_clean_replacement(
    _runtime_identity: RuntimeIdentity,
) -> None:
    """D14R.2: legacy requested_reads в запросе клиента отклоняется."""
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r0",
            broker_id="b1",
            namespace="ns",
        ),
    )
    req = make_request_envelope(
        identity=_runtime_identity,
        message_id="m-legacy",
        parent_message_id=None,
        from_agent="t",
        to_agent=None,
        msg_type="service.request",
        payload={
            "service": "memory.query_context",
            "request_id": "r-legacy",
            "goal": "g",
            "project_root": "/tmp",
            "requested_reads": [{"path": "x.py", "reason": "legacy"}],
        },
    )
    out = w.handle(req)
    assert out.get("ok") is False
    err = out.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "legacy_contract_rejected"
