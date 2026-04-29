"""G14R.2: DTO runtime_step, реестр команд, строгий W14 output (W14 G14R.2)."""

from __future__ import annotations

import json
import pytest

from agent_core.runtime.agent_memory_runtime_contract import (
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
    """schema_version is the only field runtime may repair locally."""
    o = json.loads(_minimal_w14_envelope())
    o["schema_version"] = "1.0"
    o["extra"] = "nope"
    with pytest.raises(W14CommandParseError, match="not agent_memory"):
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
