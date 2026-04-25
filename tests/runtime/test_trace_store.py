from __future__ import annotations

from pathlib import Path

from agent_core.runtime.trace_store import JsonlTraceStore, TraceRow


def test_trace_store_append_and_filter(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    st = JsonlTraceStore(p)
    st.append(TraceRow(data={"chat_id": "a", "broker_id": "b1", "type": "x"}))
    st.append(TraceRow(data={"chat_id": "a", "broker_id": "b2", "type": "y"}))
    st.append(TraceRow(data={"chat_id": "b", "broker_id": "b3", "type": "z"}))
    rows = list(st.filter_rows(chat_id="a"))
    assert len(rows) == 2
    rows2 = list(st.filter_rows(chat_id="a", broker_id="b2"))
    assert rows2[0].data["type"] == "y"


def test_trace_row_json_is_single_line() -> None:
    row = TraceRow(data={"x": "a\nb"})
    line = row.to_json_line()
    assert "\n" not in line
