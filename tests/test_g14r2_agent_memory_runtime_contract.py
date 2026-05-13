"""G14R.2: DTO runtime_step, реестр команд, строгий W14 output (W14 G14R.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_memory.pag_runtime import PagRuntimeConfig
from agent_memory.sqlite_pag import SqlitePagStore
from ailit_base.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
)
from agent_memory.agent_memory_query_pipeline import (
    W14_PLAN_TRAVERSAL_SYSTEM,
    _w14_repair_error_targets_in_progress_legacy_status,
    _w14_repair_system_message,
    _w14_repair_user_instruction,
)
from agent_memory.agent_memory_runtime_contract import (
    AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
    AgentMemoryCommandRegistry,
    AgentMemoryRuntimeStepV1,
    InvalidRuntimeTransitionError,
    UnknownAgentMemoryCommandError,
    UnknownRuntimeStateError,
    W14CommandParseError,
    assert_runtime_state_transition,
    parse_memory_query_pipeline_llm_text,
    parse_memory_query_pipeline_llm_text_result,
    parse_w14_command_output_text_strict,
    validate_or_canonicalize_w14_command_envelope_object,
    validate_w14_command_envelope_object,
)
from ailit_runtime.models import RuntimeIdentity, make_request_envelope
from agent_memory.pag_graph_write_service import PagGraphWriteService
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


class _OneShotProvider:
    def __init__(self, body: str) -> None:
        self._body = body
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "g14r2-uc-mock"

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
            provider_metadata={"mock": "g14r2-uc"},
            raw_debug_payload=None,
        )

    def stream(self, request: ChatRequest) -> None:
        raise NotImplementedError


def _uc_env(
    root: Path,
    *,
    goal: str,
    path: str,
    qid: str = "mem-uc-g14r2",
) -> object:
    ident = RuntimeIdentity(
        runtime_id="rt-uc",
        chat_id="c-uc-g14r2",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns-uc-g14r2",
    )
    return make_request_envelope(
        identity=ident,
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


def _minimal_w14_envelope() -> str:
    o = {
        "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
        "command": "plan_traversal",
        "command_id": "cmd-1",
        "status": "ok",
        "payload": {"actions": []},
        "decision_summary": "d",
        "violations": [],
    }
    return json.dumps(o, ensure_ascii=False)


def test_runtime_step_rejects_unknown_state() -> None:
    """C14R.8: неизвестный ``state`` нельзя присвоить DTO."""
    with pytest.raises(UnknownRuntimeStateError):
        AgentMemoryRuntimeStepV1.from_mapping(
            {
                "schema_version": "agent_memory_runtime_step.v1",
                "step_id": "rt-1",
                "query_id": "q1",
                "state": "not_a_runtime_state",
            },
        )


def test_command_registry_rejects_unknown_command() -> None:
    """C14R.4: команда вне реестра — ``unknown_command``."""
    with pytest.raises(UnknownAgentMemoryCommandError):
        AgentMemoryCommandRegistry.resolve("not_a_w14_command")


def test_runtime_step_transition_table_blocks_invalid_transition() -> None:
    """C14R.8: запрещённый переход (например start -> finish)."""
    with pytest.raises(InvalidRuntimeTransitionError):
        assert_runtime_state_transition("start", "finish")


def test_command_output_rejects_prose_around_json() -> None:
    """
    W14: ответ с прозой + JSON не принимается для
    ``agent_memory_command_output.v1`` (только цельный JSON).
    """
    body = _minimal_w14_envelope()
    with pytest.raises(W14CommandParseError, match="w14 command output"):
        parse_memory_query_pipeline_llm_text(
            f"Here is the result:\n{body}",
        )


def test_command_output_rejects_unknown_top_level_field() -> None:
    o = json.loads(_minimal_w14_envelope())
    o["extra_field"] = 1
    with pytest.raises(W14CommandParseError, match="unknown_fields"):
        parse_w14_command_output_text_strict(json.dumps(o))


def test_valid_w14_parsed_from_pipeline_parser() -> None:
    t = _minimal_w14_envelope()
    d = parse_memory_query_pipeline_llm_text(t)
    assert d["command"] == "plan_traversal"
    assert d["schema_version"] == AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA


def test_w14_schema_version_mismatch_can_be_canonicalized() -> None:
    """W14-like JSON with only wrong schema_version is canonicalized."""
    o = json.loads(_minimal_w14_envelope())
    o["schema_version"] = "1.0"
    res = parse_memory_query_pipeline_llm_text_result(json.dumps(o))
    assert res.normalized is True
    assert res.from_schema_version == "1.0"
    assert res.obj["schema_version"] == AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA


def test_w14_schema_version_canonicalization_requires_exact_rest_shape(
) -> None:
    """Лишние поля не снимаются локальной каноникализацией."""
    o = json.loads(_minimal_w14_envelope())
    o["schema_version"] = "1.0"
    o["extra"] = "nope"
    with pytest.raises(W14CommandParseError, match="unknown_fields"):
        parse_memory_query_pipeline_llm_text_result(json.dumps(o))


def test_legacy_planner_allows_json_extract() -> None:
    """G13 planner JSON внутри текста с ``{...}`` — не W14 envelope."""
    inner = {
        "partial": False,
        "decision_summary": "x",
        "requested_reads": [],
        "c_upserts": [],
    }
    wrapped = f"prefix text then {json.dumps(inner)} trailing"
    d = parse_memory_query_pipeline_llm_text(wrapped)
    assert d.get("decision_summary") == "x"


def test_w14_uc01_canonical_envelope_avoids_superfluous_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-01: schema 1.0 только — один LLM-вызов, без w14_contract_failure."""
    db = tmp_path / "uc01.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    rm = tmp_path / "README.md"
    rm.write_text("# Demo\n", encoding="utf-8")
    wseed = PagGraphWriteService(
        SqlitePagStore(PagRuntimeConfig.from_env().db_path),
    )
    wseed.upsert_node(
        namespace="ns-uc-g14r2",
        node_id="C:README.md#intro",
        level="C",
        kind="section",
        path="README.md",
        title="intro",
        summary="About",
        attrs={},
        fingerprint="fp1",
        staleness_state="fresh",
    )
    pl: dict[str, object] = {
        "finish": True,
        "status": "complete",
        "selected_results": [
            {
                "kind": "c_summary",
                "path": "README.md",
                "node_id": "C:README.md#intro",
                "summary": None,
                "read_lines": [],
                "reason": "uc01",
            },
        ],
        "decision_summary": "d",
        "recommended_next_step": "",
    }
    o: dict[str, object] = {
        "schema_version": "1.0",
        "command": "finish_decision",
        "command_id": "fd-uc01",
        "status": "ok",
        "payload": pl,
        "decision_summary": "d",
        "violations": [],
    }
    prov = _OneShotProvider(json.dumps(o, ensure_ascii=False))
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-uc-g14r2",
            broker_id="b1",
            namespace="ns-uc-g14r2",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    out = worker.handle(
        _uc_env(tmp_path, goal="о чем readme", path="README.md"),
    )
    assert out.get("ok") is True
    assert len(prov.calls) == 1
    msl: object = (out.get("payload") or {}).get("memory_slice")
    assert isinstance(msl, dict)
    assert msl.get("w14_contract_failure") is not True


def test_w14_uc02_command_id_restored_from_runtime_without_stale_repair_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-02: 1.0 + null command_id + success + runtime id — один LLM-вызов."""
    db = tmp_path / "uc02.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    rm = tmp_path / "README.md"
    rm.write_text("# X\n", encoding="utf-8")
    wseed = PagGraphWriteService(
        SqlitePagStore(PagRuntimeConfig.from_env().db_path),
    )
    wseed.upsert_node(
        namespace="ns-uc-g14r2",
        node_id="C:README.md#x",
        level="C",
        kind="section",
        path="README.md",
        title="x",
        summary="S",
        attrs={},
        fingerprint="fp2",
        staleness_state="fresh",
    )
    pl: dict[str, object] = {
        "finish": True,
        "status": "complete",
        "selected_results": [
            {
                "kind": "c_summary",
                "path": "README.md",
                "node_id": "C:README.md#x",
                "summary": None,
                "read_lines": [],
                "reason": "uc02",
            },
        ],
        "decision_summary": "d",
        "recommended_next_step": "",
    }
    o = {
        "schema_version": "1.0",
        "command": "finish_decision",
        "command_id": None,
        "status": "success",
        "payload": pl,
        "decision_summary": "d",
        "violations": [],
    }
    prov = _OneShotProvider(json.dumps(o, ensure_ascii=False))
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-uc-g14r2",
            broker_id="b1",
            namespace="ns-uc-g14r2",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    out = worker.handle(
        _uc_env(tmp_path, goal="g", path="README.md", qid="q-uc02"),
    )
    assert out.get("ok") is True
    assert len(prov.calls) == 1
    msl2: object = (out.get("payload") or {}).get("memory_slice")
    assert isinstance(msl2, dict)
    assert msl2.get("w14_contract_failure") is not True


def test_w14_uc01_canonicalization_emits_compact_schema_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-01: journal memory.command.normalized, from/to schema_version."""
    db = tmp_path / "uc01obs.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "r.md").write_text("#\n", encoding="utf-8")
    wseed = PagGraphWriteService(
        SqlitePagStore(PagRuntimeConfig.from_env().db_path),
    )
    wseed.upsert_node(
        namespace="ns-uc-g14r2",
        node_id="C:r.md#1",
        level="C",
        kind="section",
        path="r.md",
        title="t",
        summary="S",
        attrs={},
        fingerprint="fp3",
        staleness_state="fresh",
    )
    pl: dict[str, object] = {
        "finish": True,
        "status": "complete",
        "selected_results": [
            {
                "kind": "c_summary",
                "path": "r.md",
                "node_id": "C:r.md#1",
                "summary": None,
                "read_lines": [],
                "reason": "o",
            },
        ],
        "decision_summary": "d",
        "recommended_next_step": "",
    }
    o: dict[str, object] = {
        "schema_version": "1.0",
        "command": "finish_decision",
        "command_id": "x",
        "status": "ok",
        "payload": pl,
        "decision_summary": "d",
        "violations": [],
    }
    prov = _OneShotProvider(json.dumps(o, ensure_ascii=False))
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-uc-g14r2",
            broker_id="b1",
            namespace="ns-uc-g14r2",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    worker.handle(_uc_env(tmp_path, goal="g", path="r.md", qid="q-obs1"))
    rows = list(
        worker._journal.filter_rows(  # noqa: SLF001
            event_name="memory.command.normalized",
        ),
    )
    assert rows, "expected memory.command.normalized journal row"
    pay = rows[-1].payload
    assert pay.get("from_schema_version") == "1.0"
    assert pay.get("to_schema_version") == AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA


def test_w14_uc02_command_id_restore_emits_compact_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-02 observability: факт восстановления command_id в journal."""
    db = tmp_path / "uc02obs.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    (tmp_path / "z.md").write_text("#\n", encoding="utf-8")
    wseed = PagGraphWriteService(
        SqlitePagStore(PagRuntimeConfig.from_env().db_path),
    )
    wseed.upsert_node(
        namespace="ns-uc-g14r2",
        node_id="C:z.md#1",
        level="C",
        kind="section",
        path="z.md",
        title="t",
        summary="S",
        attrs={},
        fingerprint="fp4",
        staleness_state="fresh",
    )
    pl: dict[str, object] = {
        "finish": True,
        "status": "complete",
        "selected_results": [
            {
                "kind": "c_summary",
                "path": "z.md",
                "node_id": "C:z.md#1",
                "summary": None,
                "read_lines": [],
                "reason": "o",
            },
        ],
        "decision_summary": "d",
        "recommended_next_step": "",
    }
    o = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "finish_decision",
        "command_id": None,
        "status": "ok",
        "payload": pl,
        "decision_summary": "d",
        "violations": [],
    }
    prov = _OneShotProvider(json.dumps(o, ensure_ascii=False))
    worker = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-uc-g14r2",
            broker_id="b1",
            namespace="ns-uc-g14r2",
        ),
    )
    monkeypatch.setattr(worker, "_provider", prov, raising=False)
    worker.handle(_uc_env(tmp_path, goal="g", path="z.md", qid="q-obs2"))
    rows = list(
        worker._journal.filter_rows(  # noqa: SLF001
            event_name="memory.w14.command_id_restored",
        ),
    )
    assert rows, "expected memory.w14.command_id_restored journal row"
    assert rows[-1].payload.get("command_id")


def test_plan_traversal_in_progress_canonicalizes_to_ok() -> None:
    """
    T1: frozen W14 JSON; UC-02 maps in_progress to ok.

    Strict validate passes on parsed envelope.
    """
    frozen: dict[str, object] = {
        "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
        "command": "plan_traversal",
        "command_id": "w14-planner-frozen-1",
        "status": "in_progress",
        "payload": {
            "is_final": False,
            "actions": [
                {"action": "list_children", "path": "docs/README.md"},
            ],
        },
        "decision_summary": "Continue plan traversal",
        "violations": [],
    }
    text = json.dumps(frozen, ensure_ascii=False)
    plan_res = parse_memory_query_pipeline_llm_text_result(text)
    assert plan_res.obj["status"] == "ok"
    assert plan_res.normalized is True
    assert plan_res.legacy_status_from == "in_progress"
    direct = validate_or_canonicalize_w14_command_envelope_object(
        {str(k): v for k, v in frozen.items()},
    )
    assert direct.obj["status"] == "ok"
    assert direct.normalized is True
    assert direct.legacy_status_from == "in_progress"
    validate_w14_command_envelope_object(plan_res.obj)


def test_plan_traversal_schema_1_0_in_progress_parses_ok() -> None:
    """
    T2: schema 1.0 + in_progress; valid plan_traversal payload.

    Parser accepts W14 envelope (no terminal invalid path).
    """
    o: dict[str, object] = {
        "schema_version": "1.0",
        "command": "plan_traversal",
        "command_id": "w14-pt-1",
        "status": "in_progress",
        "payload": {
            "is_final": False,
            "actions": [{"action": "get_b_summary", "path": "README.md"}],
        },
        "decision_summary": "d",
        "violations": [],
    }
    text = json.dumps(o, ensure_ascii=False)
    res = parse_memory_query_pipeline_llm_text_result(text)
    assert res.obj["schema_version"] == AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA
    assert res.obj["status"] == "ok"
    assert res.normalized is True
    assert res.legacy_status_from == "in_progress"
    assert res.from_schema_version == "1.0"


def test_w14_plan_traversal_repair_uc03_system_and_instruction() -> None:
    """Wave 2: W14 whitelist status; UC-03 repair при unknown legacy."""
    needle = "только \"ok\", \"partial\" или \"refuse\""
    assert needle in W14_PLAN_TRAVERSAL_SYSTEM
    assert "in_progress" in W14_PLAN_TRAVERSAL_SYSTEM
    assert "payload.is_final" in W14_PLAN_TRAVERSAL_SYSTEM
    assert "payload.actions" in W14_PLAN_TRAVERSAL_SYSTEM
    err = "unknown_legacy_w14_status:'in_progress'"
    assert _w14_repair_error_targets_in_progress_legacy_status(err) is True
    sys_msg = _w14_repair_system_message(err)
    assert "UC-03" in sys_msg
    assert "payload.is_final=false" in sys_msg or "is_final=false" in sys_msg
    assert "не сохраняй" in sys_msg
    inst = _w14_repair_user_instruction(err)
    assert "ok|partial|refuse" in inst
    assert "in_progress" in inst
    base_only = _w14_repair_system_message("invalid_w14_envelope_status")
    assert "UC-03" not in base_only
