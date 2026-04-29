"""
G14R.11: интеграция query_context, отказ от G13 planner JSON, smoke контракты.

План: ``plan/14-agent-memory-runtime.md`` §G14R.11.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.memory.pag_runtime import PagRuntimeConfig
from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
)
from agent_core.runtime.models import RuntimeIdentity, make_request_envelope
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService
from agent_core.runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)

_REPO = Path(__file__).resolve().parents[1]
_RUNTIME = _REPO / "tools" / "agent_core" / "runtime"
_LEGACY_FORBIDDEN = ("semantic_c_extraction", "memory_c_extractor_prompt")


class _OneShotProvider:
    def __init__(self, body: str) -> None:
        self._body = body
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "g14r11-mock"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        self.calls.append(request)
        return NormalizedChatResponse(
            text_parts=(self._body,),
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            usage=NormalizedUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
            provider_metadata={"mock": "g14r11"},
            raw_debug_payload=None,
        )

    def stream(self, request: ChatRequest) -> None:
        raise NotImplementedError


def _rt_ident(namespace: str = "ns-g14r11") -> RuntimeIdentity:
    return RuntimeIdentity(
        runtime_id="rt-g14r11",
        chat_id="c-g14r11",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace=namespace,
    )


def _w14_finish(
    *,
    path: str,
    node_id: str,
    sub_status: str = "complete",
    rns: str = "",
) -> str:
    pl: dict[str, object] = {
        "finish": True,
        "status": sub_status,
        "selected_results": [
            {
                "kind": "c_summary",
                "path": path,
                "node_id": node_id,
                "summary": None,
                "read_lines": [],
                "reason": "g14r11",
            },
        ],
        "decision_summary": "d",
        "recommended_next_step": rns,
    }
    o: dict[str, object] = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "finish_decision",
        "command_id": "fd-g14r11",
        "status": "ok",
        "payload": pl,
        "decision_summary": "d",
        "violations": [],
    }
    return json.dumps(o, ensure_ascii=False)


def _env(
    root: Path,
    *,
    goal: str,
    path: str,
    qid: str = "mem-g14r11-1",
) -> object:
    return make_request_envelope(
        identity=_rt_ident(),
        message_id="m1",
        parent_message_id=None,
        from_agent="AgentWork",
        to_agent="AgentMemory:global",
        msg_type="service.request",
        payload={
            "service": "memory.query_context",
            "request_id": "r1",
            "goal": goal,
            "path": path,
            "query_id": qid,
            "project_root": str(root),
        },
    )


def test_query_context_runtime_happy_path_repo_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: repo question → finish_decision c_summary (README)."""
    db = tmp_path / "p.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    rm = tmp_path / "README.md"
    rm.write_text("# Demo\nAilit test repo.\n", encoding="utf-8")
    store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    w = PagGraphWriteService(store)
    w.upsert_node(
        namespace="ns-g14r11",
        node_id="C:README.md#intro",
        level="C",
        kind="section",
        path="README.md",
        title="intro",
        summary="About the project",
        attrs={},
        fingerprint="fp1",
        staleness_state="fresh",
    )
    prov = _OneShotProvider(
        _w14_finish(
            path="README.md",
            node_id="C:README.md#intro",
        ),
    )
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r11",
            broker_id="b1",
            namespace="ns-g14r11",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    out = worker.handle(
        _env(
            tmp_path,
            goal="о чем репозиторий",
            path="README.md",
        ),
    )
    assert out.get("ok") is True
    pl: object = out.get("payload")
    assert isinstance(pl, dict)
    amr: object = pl.get("agent_memory_result")
    assert isinstance(amr, dict)
    assert amr.get("status") in ("complete", "partial", "blocked")
    res: object = amr.get("results")
    assert isinstance(res, list) and res
    assert res[0].get("path") == "README.md"
    first = str(prov.calls[0].messages[0].content or "")
    assert "plan_traversal" in first or "AgentMemory" in first


def test_query_context_runtime_happy_path_file_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сквозной happy path: вопрос по известному файлу."""
    db = tmp_path / "p2.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "a.py").write_text("X = 1\n", encoding="utf-8")
    wseed = PagGraphWriteService(
        SqlitePagStore(PagRuntimeConfig.from_env().db_path),
    )
    wseed.upsert_node(
        namespace="ns-g14r11",
        node_id="C:a.py#x",
        level="C",
        kind="name",
        path="a.py",
        title="X",
        summary="const",
        attrs={},
        fingerprint="fpa",
        staleness_state="fresh",
    )
    prov = _OneShotProvider(
        _w14_finish(
            path="a.py",
            node_id="C:a.py#x",
        ),
    )
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r11",
            broker_id="b1",
            namespace="ns-g14r11",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    out = worker.handle(
        _env(
            tmp_path,
            goal="что в файле a.py",
            path="a.py",
            qid="mem-file-q",
        ),
    )
    assert out.get("ok") is True
    amr2: object = (out.get("payload") or {}).get("agent_memory_result")
    assert isinstance(amr2, dict)
    r2: object = amr2.get("results")
    assert isinstance(r2, list) and r2
    assert r2[0].get("path") == "a.py"


def test_query_context_runtime_partial_when_budget_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    finish_decision с payload.status=partial → итог partial, есть next step.
    (аналог исчерпания/неполного evidence в одном query.)
    """
    db = tmp_path / "p3.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "b.py").write_text("y=2\n", encoding="utf-8")
    wseed = PagGraphWriteService(
        SqlitePagStore(PagRuntimeConfig.from_env().db_path),
    )
    wseed.upsert_node(
        namespace="ns-g14r11",
        node_id="C:b.py#1",
        level="C",
        kind="name",
        path="b.py",
        title="y",
        summary="n",
        attrs={},
        fingerprint="fpb",
        staleness_state="fresh",
    )
    o = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "finish_decision",
        "command_id": "fd-partial",
        "status": "ok",
        "payload": {
            "finish": True,
            "status": "partial",
            "selected_results": [
                {
                    "kind": "c_summary",
                    "path": "b.py",
                    "node_id": "C:b.py#1",
                    "summary": None,
                    "read_lines": [],
                    "reason": "p",
                },
            ],
            "decision_summary": "partial",
            "recommended_next_step": "добавить subgoal",
        },
        "decision_summary": "partial",
        "violations": [],
    }
    prov = _OneShotProvider(json.dumps(o, ensure_ascii=False))
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r11",
            broker_id="b1",
            namespace="ns-g14r11",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    out = worker.handle(
        _env(tmp_path, goal="g", path="b.py", qid="q-partial-budget"),
    )
    assert out.get("ok") is True
    pl3: object = out.get("payload")
    assert isinstance(pl3, dict) and pl3.get("partial") is True
    am3: object = pl3.get("agent_memory_result")
    assert isinstance(am3, dict)
    assert am3.get("status") == "partial"
    nxt: object = pl3.get("recommended_next_step") or am3.get(
        "recommended_next_step",
    )
    assert "subgoal" in str(nxt) or nxt is not None


def test_legacy_requested_reads_disabled_after_w14r(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    D14R.2: G13 planner JSON (c_upserts) does not write PAG nodes (G14R.11).
    """
    db = tmp_path / "p4.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "legacy.py").write_text("z=3\n", encoding="utf-8")
    legacy_plan = {
        "selected_projects": [],
        "c_upserts": [
            {
                "node_id": "C:legacy:should-not-exist",
                "level": "C",
                "kind": "chunk",
                "path": "legacy.py",
                "title": "t",
                "summary": "s",
                "fingerprint": "fpL",
            },
        ],
        "requested_reads": [{"path": "legacy.py", "reason": "r"}],
        "decision_summary": "x",
        "partial": True,
    }
    prov = _OneShotProvider(json.dumps(legacy_plan, ensure_ascii=False))
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r11",
            broker_id="b1",
            namespace="ns-g14r11",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    out = worker.handle(
        _env(tmp_path, goal="g", path="legacy.py", qid="q-legacy"),
    )
    assert out.get("ok") is True
    st = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    assert (
        st.fetch_node(
            namespace="ns-g14r11",
            node_id="C:legacy:should-not-exist",
        )
        is None
    )


def test_w14_no_runtime_imports_from_legacy_c_modules() -> None:
    """
    G14R.11: runtime не импортирует legacy C extraction по строкам import.
    """
    for path in sorted(_RUNTIME.rglob("*.py")):
        if "test" in path.name:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("import ") or " import " in s:
                for sub in _LEGACY_FORBIDDEN:
                    if sub in line and sub in s:
                        msg = f"{path.relative_to(_REPO)}:{i}: {line!r}"
                        raise AssertionError(
                            f"W14 runtime не импортирует legacy C: {msg}",
                        )
