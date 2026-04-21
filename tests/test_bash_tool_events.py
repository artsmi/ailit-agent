"""Тесты emit_bash_shell_telemetry (этап C)."""

from __future__ import annotations

from agent_core.session.bash_tool_events import emit_bash_shell_telemetry
from agent_core.tool_runtime.executor import ToolInvocation, ToolRunResult


def test_emit_bash_telemetry_chunks_and_finished() -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(et: str, pl: dict[str, object]) -> None:
        emitted.append((et, pl))

    inv = ToolInvocation(
        call_id="c1",
        tool_name="run_shell",
        arguments_json='{"command": "echo hi"}',
    )
    res = ToolRunResult(
        call_id="c1",
        tool_name="run_shell",
        content=(
            "exit_code: 0\n"
            "timed_out: false\n"
            "truncated: false\n\n"
            "--- stdout ---\n"
            "hi\n"
            "--- stderr ---\n"
            "(empty)\n"
        ),
        error=None,
    )
    emit_bash_shell_telemetry(emit, inv, res)
    types = [t for t, _ in emitted]
    assert "bash.output_delta" in types
    assert "bash.finished" in types
    assert "bash.execution" in types
    fin = next(pl for t, pl in emitted if t == "bash.finished")
    assert fin["call_id"] == "c1"
    assert fin["ok"] is True
    assert fin["byte_len"] > 0
    ex = next(pl for t, pl in emitted if t == "bash.execution")
    assert ex["command"] == "echo hi"
    assert ex["exit_code"] == 0


def test_emit_bash_skips_non_shell() -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(et: str, pl: dict[str, object]) -> None:
        emitted.append((et, pl))

    inv = ToolInvocation(
        call_id="x",
        tool_name="echo",
        arguments_json='{"message":"a"}',
    )
    res = ToolRunResult(
        call_id="x",
        tool_name="echo",
        content="a",
        error=None,
    )
    emit_bash_shell_telemetry(emit, inv, res)
    assert emitted == []
