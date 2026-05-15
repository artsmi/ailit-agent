"""
G14R.11: интеграция query_context, отказ от G13 planner JSON, smoke контракты.

План: ``plan/14-agent-memory-runtime.md`` §G14R.11.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from agent_memory.storage.pag_runtime import PagRuntimeConfig
from agent_memory.storage.sqlite_pag import SqlitePagStore
from ailit_base.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
)
from agent_memory.contracts.agent_memory_runtime_contract import (
    AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
)
from agent_memory.contracts.agent_memory_result_v1 import (
    AGENT_MEMORY_RESULT_V1,
    build_agent_memory_result_v1,
)
from agent_memory.config.agent_memory_config import (
    load_or_create_agent_memory_config,
)
from ailit_runtime.models import RuntimeIdentity, make_request_envelope
from agent_memory.pag.pag_graph_trace import MEMORY_W14_GRAPH_HIGHLIGHT_EVENT
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)

_REPO = Path(__file__).resolve().parents[1]
_RUNTIME = _REPO / "ailit" / "agent_memory"
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


class _SeqProvider:
    def __init__(self, bodies: list[str]) -> None:
        self._bodies = list(bodies)
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "g14r11-seq"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        self.calls.append(request)
        body = self._bodies.pop(0) if self._bodies else "not json"
        return NormalizedChatResponse(
            text_parts=(body,),
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            usage=NormalizedUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
            provider_metadata={"mock": "g14r11-seq"},
            raw_debug_payload=None,
        )

    def stream(self, request: ChatRequest) -> None:
        raise NotImplementedError


_PLANNER_SYS_PLAN_TRAVERSAL = "команду AgentMemory plan_traversal"


class _InProgressPlanFirstRuntimeProvider:
    """
    Первый planner-раунд: валидный plan_traversal с legacy top-level
    ``in_progress`` (UC-02 механика); далее тот же контракт, что
    ``_RuntimeProvider``.
    """

    def __init__(self) -> None:
        self._rt = _RuntimeProvider()
        self._first_planner = True
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "g14r11-uc03-t3"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        self.calls.append(request)
        sys0 = str(request.messages[0].content or "")
        if self._first_planner and _PLANNER_SYS_PLAN_TRAVERSAL in sys0:
            self._first_planner = False
            body = _w14_plan_traversal_in_progress_envelope()
            return NormalizedChatResponse(
                text_parts=(body,),
                tool_calls=(),
                finish_reason=FinishReason.STOP,
                usage=NormalizedUsage(
                    input_tokens=1,
                    output_tokens=1,
                    total_tokens=2,
                ),
                provider_metadata={"mock": "g14r11-uc03-t3"},
                raw_debug_payload=None,
            )
        return self._rt.complete(request)

    def stream(self, request: ChatRequest) -> None:
        raise NotImplementedError


class _RuntimeProvider:
    """Provider that returns W14 JSON for planner, summaries and finish."""

    def __init__(self) -> None:
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "g14r11-runtime"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        self.calls.append(request)
        content = str(request.messages[-1].content or "")
        body = _w14_plan()
        if "summarize_c" in content:
            body = _w14_command(
                command="summarize_c",
                payload={
                    "summary": "compact C summary",
                    "semantic_tags": [],
                    "important_lines": [],
                    "claims": [],
                    "refusal_reason": "",
                },
            )
        elif "summarize_b" in content:
            body = _w14_command(
                command="summarize_b",
                payload={
                    "summary": "compact B summary",
                    "child_refs": [],
                    "missing_children": [],
                    "confidence": 1.0,
                    "refusal_reason": "",
                },
            )
        elif "finish_decision" in content:
            selected: list[object] = []
            try:
                raw = json.loads(content)
                payload = raw.get("payload", {})
                if isinstance(payload, dict):
                    sr = payload.get("selected_results", [])
                    if isinstance(sr, list):
                        selected = sr
            except json.JSONDecodeError:
                selected = []
            body = _w14_command(
                command="finish_decision",
                payload={
                    "finish": True,
                    "status": "complete" if selected else "partial",
                    "selected_results": selected,
                    "decision_summary": "done",
                    "recommended_next_step": "",
                },
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
            provider_metadata={"mock": "g14r11-runtime"},
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


def _w14_command(command: str, payload: dict[str, object]) -> str:
    o: dict[str, object] = {
        "schema_version": "agent_memory_command_output.v1",
        "command": command,
        "command_id": f"cmd-{command}",
        "status": "ok",
        "payload": payload,
        "decision_summary": "d",
        "violations": [],
    }
    return json.dumps(o, ensure_ascii=False)


def _w14_plan(
    *,
    schema_version: str = "agent_memory_command_output.v1",
    extra: bool = False,
) -> str:
    o: dict[str, object] = {
        "schema_version": schema_version,
        "command": "plan_traversal",
        "command_id": "pt-g14r11",
        "status": "ok",
        "payload": {
            "actions": [
                {"action": "list_children", "path": "."},
            ],
            "is_final": False,
            "final_answer_basis": None,
        },
        "decision_summary": "plan",
        "violations": [],
    }
    if extra:
        o["extra"] = "bad"
    return json.dumps(o, ensure_ascii=False)


def _w14_plan_traversal_in_progress_envelope() -> str:
    """Frozen W14 plan_traversal с top-level ``in_progress`` (UC-02 narrow)."""
    o: dict[str, object] = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "plan_traversal",
        "command_id": "pt-in-progress",
        "status": "in_progress",
        "payload": {
            "actions": [
                {"action": "list_children", "path": "."},
            ],
            "is_final": False,
            "final_answer_basis": None,
        },
        "decision_summary": "plan",
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


def test_w14_invalid_json_does_not_grow_pag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad planner JSON must not write A/B/C/D nodes in W14 strict path."""
    db = tmp_path / "invalid-json.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "g.py").write_text(
        "def g() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    prov = _OneShotProvider("not json")
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
            goal="изучи g.py",
            path="g.py",
        ),
    )
    assert out.get("ok") is True
    store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    assert store.list_nodes(namespace="ns-g14r11") == []


def test_w14_command_rejected_does_not_grow_pag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W14 envelope inside markdown/prose is rejected without PAG writes."""
    db = tmp_path / "rejected-command.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "g.py").write_text(
        "def g() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    body = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "plan_traversal",
        "command_id": "pt-bad",
        "status": "ok",
        "payload": {"actions": []},
        "decision_summary": "d",
        "violations": [],
    }
    prov = _OneShotProvider(f"```json\n{json.dumps(body)}\n```")
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
            goal="изучи g.py",
            path="g.py",
        ),
    )
    assert out.get("ok") is True
    store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    assert store.list_nodes(namespace="ns-g14r11") == []


def test_w14_schema_repair_retry_accepts_fixed_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-canonical schema error gets one repair retry and then continues."""
    db = tmp_path / "repair-ok.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "g.py").write_text(
        "def g() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    prov = _SeqProvider(
        [
            _w14_plan(schema_version="1.0", extra=True),
            _w14_plan(),
        ],
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
            goal="изучи g.py",
            path="g.py",
        ),
    )
    assert out.get("ok") is True
    assert len(prov.calls) >= 2
    pl = out.get("payload")
    assert isinstance(pl, dict)
    assert pl.get("decision_summary") == "plan"


def test_w14_schema_repair_failure_returns_empty_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed repair gives partial W14 contract failure without PAG writes."""
    db = tmp_path / "repair-fail.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "g.py").write_text(
        "def g() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    prov = _SeqProvider(
        [
            _w14_plan(schema_version="1.0", extra=True),
            _w14_plan(schema_version="1.0", extra=True),
        ],
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
            goal="изучи g.py",
            path="g.py",
        ),
    )
    assert out.get("ok") is True
    assert len(prov.calls) == 2
    pl = out.get("payload")
    assert isinstance(pl, dict)
    ms = pl.get("memory_slice")
    assert isinstance(ms, dict)
    assert ms.get("reason") == "w14_command_output_invalid"
    assert ms.get("w14_contract_failure") is True
    assert ms.get("reason") not in ("no_pag_slice", "path_hint_fallback")
    amr = pl.get("agent_memory_result")
    assert isinstance(amr, dict)
    assert amr.get("results") == []
    store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    assert store.list_nodes(namespace="ns-g14r11") == []


def test_w14_plan_traversal_repair_uc03_tc_t3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    TC-T3 / TC-UC03-REPAIR (wave 3): первый ответ — plan_traversal +
    ``in_progress``.

    Механическая канонизация UC-02; без repair-раунда и без terminal
    ``w14_contract_failure`` / ``fix_memory_llm_json`` из-за статуса шага.
    """
    db = tmp_path / "tc-t3-uc03.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "g.py").write_text(
        "def g() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    prov = _InProgressPlanFirstRuntimeProvider()
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
            goal="изучи g.py",
            path="g.py",
            qid="mem-tc-t3-uc03",
        ),
    )
    assert out.get("ok") is True
    pl: object = out.get("payload")
    assert isinstance(pl, dict)
    assert pl.get("recommended_next_step") != "fix_memory_llm_json"
    msl: object = pl.get("memory_slice")
    assert isinstance(msl, dict)
    assert msl.get("w14_contract_failure") is not True
    assert msl.get("reason") != "w14_command_output_invalid"
    amr: object = pl.get("agent_memory_result")
    assert isinstance(amr, dict)
    res: object = amr.get("results")
    assert isinstance(res, list) and res
    assert res[0].get("path") == "g.py"
    store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    b_g = store.fetch_node(
        namespace="ns-g14r11",
        node_id="B:g.py",
    )
    assert b_g is not None
    norm_rows = list(
        worker._journal.filter_rows(  # noqa: SLF001
            event_name="memory.command.normalized",
        ),
    )
    assert norm_rows, "expected memory.command.normalized journal row"
    pay = norm_rows[-1].payload
    assert str(pay.get("from_status") or "").strip().lower() == "in_progress"
    assert pay.get("to_schema_version") == AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA
    assert len(prov.calls) >= 2


def test_agent_memory_result_does_not_project_a_or_b_as_c_summary() -> None:
    """Compatibility projection must not turn A/B node ids into C summaries."""
    amr = build_agent_memory_result_v1(
        query_id="q",
        status="partial",
        memory_slice={
            "kind": "memory_slice",
            "node_ids": ["A:repo", "B:file.py"],
            "target_file_paths": [],
            "injected_text": "fallback text",
            "reason": "fallback",
        },
        partial=True,
        decision_summary="d",
        recommended_next_step="n",
    )
    assert amr["results"] == []


def _install_stdout_line_capture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    lines: list[str] = []
    buf = StringIO()

    def _write(s: str) -> int:
        buf.write(s)
        if s.endswith("\n"):
            line = s[:-1].strip()
            if line:
                lines.append(line)
        return len(s)

    monkeypatch.setattr("sys.stdout.write", _write)
    monkeypatch.setattr("sys.stdout.flush", lambda: None)
    return lines


def _topic_event_names_from_stdout_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        inner = row.get("payload")
        if not isinstance(inner, dict) or inner.get("type") != "topic.publish":
            continue
        en = inner.get("event_name")
        if isinstance(en, str):
            out.append(en)
    return out


def test_w14_plan_traversal_pag_trace_before_single_graph_highlight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.2: pag.* в stdout до одного memory.w14.graph_highlight за turn."""
    db = tmp_path / "trace-order.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "a.py").write_text(
        "def a() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "def b() -> int:\n    return 2\n",
        encoding="utf-8",
    )
    cap_lines = _install_stdout_line_capture(monkeypatch)
    prov = _RuntimeProvider()
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
            goal="посмотри каждый файл репозитория",
            path="",
        ),
    )
    assert out.get("ok") is True
    events = _topic_event_names_from_stdout_lines(cap_lines)
    hl_idx = [
        i
        for i, e in enumerate(events)
        if e == MEMORY_W14_GRAPH_HIGHLIGHT_EVENT
    ]
    assert len(hl_idx) == 1
    pag_idx = [i for i, e in enumerate(events) if e.startswith("pag.")]
    assert pag_idx
    assert max(pag_idx) < hl_idx[0]


def test_w14_all_files_processes_multiple_b_not_only_readme(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-files goal materializes multiple B files and real C results."""
    db = tmp_path / "runtime.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "a.py").write_text(
        "def a() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "def b() -> int:\n    return 2\n",
        encoding="utf-8",
    )
    prov = _RuntimeProvider()
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
            goal="посмотри каждый файл репозитория",
            path="",
        ),
    )
    assert out.get("ok") is True
    store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
    b_paths = {
        n.path for n in store.list_nodes(namespace="ns-g14r11", level="B")
    }
    assert {"README.md", "a.py", "b.py"}.issubset(b_paths)
    amr = (out.get("payload") or {}).get("agent_memory_result")
    assert isinstance(amr, dict)
    results = amr.get("results")
    assert isinstance(results, list) and results
    summarize_calls = [
        c for c in prov.calls if "summarize_c" in c.messages[-1].content
    ]
    assert len(summarize_calls) >= 2


def test_w14_pipeline_emits_terminal_agent_memory_result_per_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    D-UC3-1 / UC-03: каждый memory.query_context с W14 (plan_traversal→runtime)
    возвращает потребляемый ``agent_memory_result.v1`` (не только slice).
    """
    db = tmp_path / "uc3-per-query.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "a.py").write_text(
        "def a() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    prov = _RuntimeProvider()
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r11",
            broker_id="b1",
            namespace="ns-g14r11",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    for qid in ("uc3-mem-query-1", "uc3-mem-query-2"):
        out = worker.handle(
            _env(
                tmp_path,
                goal="посмотри каждый файл репозитория",
                path="",
                qid=qid,
            ),
        )
        assert out.get("ok") is True
        pl: object = out.get("payload")
        assert isinstance(pl, dict)
        assert "memory_slice" in pl
        amr: object = pl.get("agent_memory_result")
        assert isinstance(amr, dict)
        assert amr.get("schema_version") == AGENT_MEMORY_RESULT_V1
        assert str(amr.get("query_id") or "") == qid
        assert str(amr.get("status") or "") in (
            "complete",
            "partial",
            "blocked",
        )
        rt: object = amr.get("runtime_trace")
        assert isinstance(rt, dict)
        assert rt.get("final_step") == "finish"
        res: object = amr.get("results")
        assert isinstance(res, list)
        assert res, (
            "D-UC3-1: terminal agent_memory_result must include consumable "
            "results[], not slice-only completion"
        )
        for row in res:
            assert isinstance(row, dict)
            assert row.get("kind") == "c_summary"
            assert str(row.get("path") or "").strip()


def test_w14_normal_path_does_not_call_query_driven_pag_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W14 normal path must not use legacy QueryDrivenPagGrowth."""
    db = tmp_path / "runtime-no-growth.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "a.py").write_text(
        "def a() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    prov = _RuntimeProvider()
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14r11",
            broker_id="b1",
            namespace="ns-g14r11",
        ),
    )

    class BadGrowth:
        def grow(self, **_: object) -> object:
            raise AssertionError("legacy growth used")

    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    monkeypatch.setattr(worker, "_growth", BadGrowth(), raising=False)
    out = worker.handle(
        _env(
            tmp_path,
            goal="посмотри каждый файл",
            path="",
        ),
    )
    assert out.get("ok") is True


def test_agent_memory_config_uses_tmp_agent_memory_config_in_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AILIT_AGENT_MEMORY_CONFIG isolates memory.runtime defaults in tests."""
    cfg = tmp_path / "agent-memory.yaml"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(cfg))
    loaded = load_or_create_agent_memory_config()
    assert loaded.memory.runtime.max_turns == 50
    assert loaded.memory.runtime.max_selected_b == 50
    assert loaded.memory.runtime.max_c_per_b == 100
    assert loaded.memory.runtime.max_total_c == 1_000
    assert loaded.memory.runtime.max_reads_per_turn == 10
    assert loaded.memory.runtime.max_summary_chars == 150
    assert loaded.memory.runtime.max_reason_chars == 50
    assert loaded.memory.runtime.max_decision_chars == 150
    assert loaded.memory.runtime.min_child_summary_coverage == 0.5


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
        if "legacy" in path.parts:
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
