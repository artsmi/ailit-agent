"""G13.2: AgentMemory query pipeline, MemoryLlmOptimizationPolicy."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_memory.pag_runtime import PagRuntimeConfig
from agent_memory.sqlite_pag import SqlitePagStore
from agent_memory.pag_graph_write_service import PagGraphWriteService
from ailit_base.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
)
from ailit_base.providers.protocol import ChatProvider
from ailit_runtime.models import RuntimeIdentity, make_request_envelope
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


class _SeqProvider:
    """Провайдер с заранее заданными JSON-ответами (порядок фиксирован)."""

    def __init__(self, bodies: list[str]) -> None:
        self._bodies = list(bodies)
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "seq-mock"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        self.calls.append(request)
        if self._bodies:
            body = self._bodies.pop(0)
        else:
            body = '{"not":"w14_envelope"}'
        return NormalizedChatResponse(
            text_parts=(body,),
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            usage=NormalizedUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
            provider_metadata={"mock": "seq"},
            raw_debug_payload=None,
        )

    def stream(self, request: ChatRequest) -> Any:
        raise NotImplementedError


def _env(
    *,
    project_root: Path,
    path: str,
    goal: str = "t",
) -> object:
    ident = RuntimeIdentity(
        runtime_id="rt",
        chat_id="c1",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns-t",
    )
    return make_request_envelope(
        identity=ident,
        message_id="m1",
        parent_message_id=None,
        from_agent="AgentWork:c1",
        to_agent="AgentMemory:global",
        msg_type="service.request",
        payload={
            "service": "memory.query_context",
            "request_id": "r1",
            "path": path,
            "goal": goal,
            "project_root": str(project_root),
        },
    )


def _w14_finish_c_summary(
    path: str,
    node_id: str,
) -> str:
    """G14R.11: ответ планнера — только W14 finish_decision (PAG заранее)."""
    plan = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "finish_decision",
        "command_id": "cmd-finish-g13",
        "status": "ok",
        "payload": {
            "finish": True,
            "status": "complete",
            "selected_results": [
                {
                    "kind": "c_summary",
                    "path": path,
                    "node_id": node_id,
                    "summary": None,
                    "read_lines": [],
                    "reason": "g13 test",
                },
            ],
            "decision_summary": "ok",
            "recommended_next_step": "",
        },
        "decision_summary": "ok",
        "violations": [],
    }
    return json.dumps(plan, ensure_ascii=False)


def test_query_context_creates_c_node_via_structured_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "p.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    pyf = tmp_path / "m.py"
    pyf.write_text("def f():\n    return 1\n", encoding="utf-8")
    wseed = PagGraphWriteService(
        SqlitePagStore(PagRuntimeConfig.from_env().db_path),
    )
    wseed.upsert_node(
        namespace="ns-t",
        node_id="C:m.py#c1",
        level="C",
        kind="function",
        path="m.py",
        title="f",
        summary="s",
        attrs={},
        fingerprint="fp9",
        staleness_state="fresh",
    )
    prov: ChatProvider = _SeqProvider(
        [_w14_finish_c_summary("m.py", "C:m.py#c1")],
    )
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c1",
            broker_id="b1",
            namespace="ns-t",
        ),
    )
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    out = w.handle(_env(project_root=tmp_path, path="m.py", goal="find f"))
    assert out["ok"] is True
    n = out["payload"]["memory_slice"].get("node_ids") or []
    assert "C:m.py#c1" in n
    store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    c = store.fetch_node(namespace="ns-t", node_id="C:m.py#c1")
    assert c is not None
    assert prov.calls, "провайдер не вызывался"


def test_llm_requests_use_optimization_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "p2.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "x.py").write_text("a=1\n", encoding="utf-8")
    plan = {
        "c_upserts": [],
        "requested_reads": [],
        "decision_summary": "n",
        "partial": True,
        "recommended_next_step": "x",
    }
    prov: ChatProvider = _SeqProvider([json.dumps(plan)])
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c1",
            broker_id="b1",
            namespace="ns-t",
        ),
    )
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(_env(project_root=tmp_path, path="x.py", goal="g"))
    assert len(prov.calls) == 1
    ex = prov.calls[0].extra or {}
    mm = ex.get("memory_llm") or {}
    assert mm.get("phase") == "planner"
    assert prov.calls[0].max_tokens == 512
    th = (mm.get("thinking") or {}) if isinstance(mm, dict) else {}
    assert th.get("enabled") is False
    assert float(prov.calls[0].temperature) == 0.0


def test_disabled_llm_fallback_does_not_create_validated_c(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "p3.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "z.py").write_text("z=2\n", encoding="utf-8")
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c1",
            broker_id="b1",
            namespace="ns-z",
        ),
    )
    pol = replace(
        w._am_file.memory.llm_optimization,
        enabled=False,
    )
    new_mem = replace(w._am_file.memory, llm_optimization=pol)
    w._am_file = replace(w._am_file, memory=new_mem)
    w._memory_llm_policy = replace(w._memory_llm_policy, enabled=False)
    out = w.handle(
        _env(project_root=tmp_path, path="z.py", goal="goal"),
    )
    assert out["ok"] is True
    assert out["payload"]["memory_slice"].get("c_semantic_validated") is False
    assert out["payload"].get("partial") is True
