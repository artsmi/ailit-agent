"""Интеграция SessionRunner с событиями bash (этап C)."""

from __future__ import annotations

from ailit_base.models import (
    ChatMessage,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
    ToolCallNormalized,
)
from agent_work.session.loop import SessionRunner, SessionSettings
from agent_work.session.state import SessionState
from agent_work.tool_runtime.approval import ApprovalSession
from agent_work.tool_runtime.bash_tools import run_shell_tool_spec
from agent_work.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_work.tool_runtime.registry import ToolRegistry

from test_session_loop import ScriptedProvider


def test_session_emits_bash_events_for_run_shell() -> None:
    """После run_shell в событиях есть bash.*."""
    reg = ToolRegistry(
        specs={"run_shell": run_shell_tool_spec()},
        handlers={
            "run_shell": lambda _a: (
                "exit_code: 0\n"
                "timed_out: false\n"
                "truncated: false\n\n"
                "--- stdout ---\n"
                "stub\n"
                "--- stderr ---\n"
                "(empty)\n"
            ),
        },
    )
    tc = ToolCallNormalized(
        call_id="shell1",
        tool_name="run_shell",
        arguments_json='{"command": "true"}',
        stream_index=0,
        provider_name="scripted",
    )
    r1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r2 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1, r2]),
        reg,
        permission_engine=PermissionEngine(
            shell_default=PermissionDecision.ALLOW,
        ),
    )
    out = runner.run(
        [ChatMessage(role=MessageRole.USER, content="run")],
        ApprovalSession(),
        SessionSettings(model="m"),
    )
    assert out.state is SessionState.FINISHED
    types = [e.get("event_type") for e in out.events]
    assert "bash.output_delta" in types
    assert "bash.finished" in types
    assert "bash.execution" in types
