from __future__ import annotations

from agent_core.models import (
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
    ToolCallNormalized,
)
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec
from test_session_loop import ScriptedProvider


def test_kb_arguments_are_redacted_in_tool_call_started() -> None:
    specs = {
        "kb_write_fact": ToolSpec(
            name="kb_write_fact",
            description="test",
            parameters_schema={"type": "object"},
            side_effect=SideEffectClass.WRITE,
        ),
    }

    def _handler(_args: object) -> str:
        return "ok"

    reg = ToolRegistry(specs=specs, handlers={"kb_write_fact": _handler})
    resp = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(
            ToolCallNormalized(
                call_id="c1",
                tool_name="kb_write_fact",
                arguments_json='{"id":"x","body":"secret"}',
                stream_index=0,
                provider_name="scripted",
                is_complete=True,
            ),
        ),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
        ),
        provider_metadata={},
    )
    prov = ScriptedProvider([resp])
    out_rows: list[dict[str, object]] = []

    def diag_sink(row: dict[str, object]) -> None:
        out_rows.append(row)

    runner = SessionRunner(prov, reg)
    runner.run(
        [],
        ApprovalSession(),
        SessionSettings(model="mock", max_turns=1),
        diag_sink=diag_sink,
    )
    started = [
        r for r in out_rows if r.get("event_type") == "tool.call_started"
    ]
    assert started
    assert started[0].get("arguments_json") == "<redacted>"
