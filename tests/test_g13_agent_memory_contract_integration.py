"""G13.7: regression — worker, SQLite, trace, desktop-совместимые строки."""

from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agent_memory.storage.pag_runtime import PagRuntimeConfig
from agent_memory.storage.sqlite_pag import SqlitePagStore
from ailit_base.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
)
from ailit_base.providers.protocol import ChatProvider
from agent_memory.pag.link_claim_resolver import LinkClaimResolver
from ailit_runtime.models import (
    RuntimeIdentity,
    make_request_envelope,
)
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def _planner_envelope(
    *,
    project_root: Path,
    path: str,
) -> object:
    ident = RuntimeIdentity(
        runtime_id="rt",
        chat_id="c1",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="g13-int",
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
            "request_id": "r-g13-7",
            "path": path,
            "goal": "int test",
            "project_root": str(project_root),
        },
    )


class _SeqProvider:
    """Провайдер: заранее заданные JSON (план, опционально extractor)."""

    def __init__(self, bodies: list[str]) -> None:
        self._bodies = list(bodies)
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "seq-mock"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        self.calls.append(request)
        body = (
            self._bodies.pop(0)
            if self._bodies
            else '{"not":"w14_envelope"}'
        )
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


def _row_matches_desktop_pag_graph_trace_row(row: dict[str, Any]) -> bool:
    """Совпадает с ``parsePagGraphTraceDelta`` (pagGraphTraceDeltas.ts)."""
    if str(row.get("type")) != "topic.publish":
        return False
    p: Any = row.get("payload")
    if not isinstance(p, dict):
        return False
    if str(p.get("event_name")) not in (
        "pag.node.upsert",
        "pag.edge.upsert",
    ):
        return False
    inner: Any = p.get("payload")
    if not isinstance(inner, dict):
        return False
    if str(inner.get("kind") or "") not in (
        "pag.node.upsert",
        "pag.edge.upsert",
    ):
        return False
    if not str(inner.get("namespace") or "").strip():
        return False
    r0 = inner.get("rev")
    if not isinstance(r0, int) or r0 < 0:
        return False
    if str(inner.get("kind")) == "pag.edge.upsert":
        raw_e = inner.get("edges")
        if not isinstance(raw_e, list) or len(raw_e) == 0:
            return False
    return True


def _w14_finish_one(path: str, node_id: str) -> str:
    o: dict[str, Any] = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "finish_decision",
        "command_id": "cmd-g13-int",
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
                    "reason": "g13 int",
                },
            ],
            "decision_summary": "ok",
            "recommended_next_step": "",
        },
        "decision_summary": "ok",
        "violations": [],
    }
    return json.dumps(o, ensure_ascii=False)


def test_llm_to_c_edge_trace_desktop_parser_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    G13.7: PAG writes + trace, затем W14 finish_decision.

    G14R.11: G13 planner JSON не исполняется; ноды/ребро — PagGraphWriteService
    + graph_trace (тот же hook, что handle).
    """
    db = tmp_path / "g13int.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    root = tmp_path / "pro"
    root.mkdir()
    f = root / "m.py"
    f.write_text("def a():\n  pass\ndef b():\n  pass\n", encoding="utf-8")
    env = _planner_envelope(
        project_root=root,
        path="m.py",
    )
    prov: ChatProvider = _SeqProvider([_w14_finish_one("m.py", "C:m.py#a")])
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c1",
            broker_id="b1",
            namespace="g13-int",
        ),
    )
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    buf: StringIO = StringIO()
    with patch("sys.stdout", new=buf):
        store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
        write = PagGraphWriteService(store)
        hook = w._graph_trace_hook(
            env,
            request_id="r-g13-7",
            service="memory.query_context",
        )
        claims: list[dict[str, Any]] = [
            {
                "from_node_id": "C:m.py#a",
                "to_node_id": "C:m.py#b",
                "relation_type": "calls",
                "confidence": 0.9,
            },
        ]
        with store.graph_trace(hook):
            for spec in (
                {
                    "node_id": "C:m.py#a",
                    "title": "a",
                    "summary": "sa",
                    "fingerprint": "fp_a",
                },
                {
                    "node_id": "C:m.py#b",
                    "title": "b",
                    "summary": "sb",
                    "fingerprint": "fp_b",
                },
            ):
                write.upsert_node(
                    namespace="g13-int",
                    node_id=str(spec["node_id"]),
                    level="C",
                    kind="function",
                    path="m.py",
                    title=str(spec["title"]),
                    summary=str(spec["summary"]),
                    attrs={},
                    fingerprint=str(spec["fingerprint"]),
                    staleness_state="fresh",
                )
            _ = LinkClaimResolver().apply_link_claims(
                write,
                namespace="g13-int",
                claims=claims,
            )
        out: dict[str, Any] = w.handle(env)  # type: ignore[assignment]
    assert out.get("ok") is True
    st = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    assert st.fetch_node(namespace="g13-int", node_id="C:m.py#a") is not None
    assert st.fetch_node(namespace="g13-int", node_id="C:m.py#b") is not None
    gr = st.get_graph_rev(namespace="g13-int")
    assert gr >= 3
    ed = st.list_edges(namespace="g13-int", limit=20)
    assert len(ed) >= 1
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    kinds: list[str] = []
    for line in lines:
        row: dict[str, Any] = json.loads(line)
        if not _row_matches_desktop_pag_graph_trace_row(row):
            continue
        pld: Any = (row.get("payload") or {}).get("payload")
        if isinstance(pld, dict) and pld.get("kind"):
            kinds.append(str(pld.get("kind")))
    assert "pag.node.upsert" in kinds
    assert "pag.edge.upsert" in kinds
    assert prov.calls, "planner must call provider"
    ex0 = prov.calls[0].extra or {}
    mm0 = ex0.get("memory_llm") or {}
    assert (mm0.get("thinking") or {}).get("enabled") is False
    assert prov.calls[0].max_tokens == 512


def test_g13_offline_pag_write_then_pag_slice_graph_rev(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    G13.7.4: offline-запись (без trace) увеличивает graph_rev;
    CLI ``pag-slice`` возвращает тот же rev.
    """
    root: Path = Path(__file__).resolve().parents[1]
    db: Path = tmp_path / "offslice.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    store: SqlitePagStore = SqlitePagStore(db)
    store.upsert_node(
        namespace="g13-off",
        node_id="B:only.py",
        level="B",
        kind="file",
        path="only.py",
        title="only",
        summary="x",
        attrs={},
        fingerprint="f1",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
        updated_at="2026-01-01T00:00:00Z",
    )
    r0: int = store.get_graph_rev(namespace="g13-off")
    assert r0 >= 1
    code: str = f"""
import os, sys, json
os.environ["PYTHONPATH"] = {str(root / "ailit")!r}
import importlib
importlib.invalidate_caches()
# новый путь в env, как в subprocess
os.environ["AILIT_PAG_DB_PATH"] = {str(db)!r}
from ailit_cli.memory_cli import cmd_memory_pag_slice
class Args:
    namespace = "g13-off"
    db_path = {str(db)!r}
    level = None
    node_limit = 50
    node_offset = 0
    edge_limit = 50
    edge_offset = 0
sys.exit(cmd_memory_pag_slice(Args()))
"""
    r: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    data: dict[str, object] = json.loads(
        r.stdout.strip().splitlines()[-1],
    )
    assert data.get("ok") is True
    gr2: object = data.get("graph_rev", 0)
    assert isinstance(gr2, int) and gr2 == r0
