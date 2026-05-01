"""TC-1_2: CompactObservabilitySink, D4, tee stderr."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_core.runtime.compact_observability_sink import (
    CompactObservabilitySink,
    build_compact_line,
    normalize_compact_event_name,
)
from agent_core.runtime.models import (
    RuntimeIdentity,
    RuntimeNow,
    make_request_envelope,
)


def _minimal_req(*, chat_id: str = "c1", message_id: str = "m1") -> object:
    identity = RuntimeIdentity(
        runtime_id="r1",
        chat_id=chat_id,
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns",
    )
    return make_request_envelope(
        identity=identity,
        message_id=message_id,
        parent_message_id=None,
        from_agent="AgentMemory:c1",
        to_agent=None,
        msg_type="service.request",
        payload={"service": "memory.query_context"},
        now=RuntimeNow(),
    )


def test_tc_1_2_normalize_highlight() -> None:
    assert normalize_compact_event_name("memory.w14.graph_highlight") == (
        "memory.w14_graph_highlight"
    )
    line = build_compact_line(
        timestamp="2026-05-01T12:00:00+00:00",
        init_session_id="550e8400-e29b-41d4-a716-446655440000",
        chat_id="chat-a",
        event="memory.w14.graph_highlight",
        fields={"request_id": "req-1", "n_node": 2},
    )
    assert "event=memory.w14_graph_highlight" in line
    assert "memory.w14.graph_highlight" not in line
    assert line.endswith("\n")
    assert line.count("\n") == 1


def test_tc_1_2_compact_singleline() -> None:
    line = build_compact_line(
        timestamp="2026-05-01T12:00:00+00:00",
        init_session_id="u",
        chat_id="c",
        event="memory.why_llm",
        fields={"request_id": "r", "reason_id": "A1"},
    )
    inner = line[:-1]
    assert "\n" not in inner


def test_tc_1_2_compact_no_json_brace_newline() -> None:
    line = build_compact_line(
        timestamp="2026-05-01T12:00:00+00:00",
        init_session_id="u",
        chat_id="c",
        event="memory.pag_graph",
        fields={"op": "node", "rev": 1, "namespace": "ns"},
    )
    assert "{\n" not in line
    assert re.search(r"\{\s*\n", line) is None


def test_tc_1_2_tee_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "compact.log"
    sink = CompactObservabilitySink(
        compact_file=p,
        init_session_id="11111111-1111-1111-1111-111111111111",
        tee_stderr=True,
    )
    req = _minimal_req()
    sink.emit(
        req=req,
        chat_id="c1",
        event="memory.why_llm",
        fields={"request_id": "rid", "topic": "t", "reason_id": "A2"},
    )
    body = p.read_text(encoding="utf-8")
    err = capsys.readouterr().err
    assert body == err
    assert "event=memory.why_llm" in body
    assert "reason_id=A2" in body
