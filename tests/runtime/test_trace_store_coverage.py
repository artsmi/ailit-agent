"""Unit tests for runtime/trace_store.py — coverage.

Covers:
- TraceRow dataclass
- TraceRow.to_json_line()
- JsonlTraceStore.append() / iter_rows() / filter_rows()
- JsonlTraceStore empty / not found
- JsonlTraceStore.append_many()
- JsonlTraceStore.filter_rows with chat_id / broker_id / namespace / goal_id / trace_id / agent_instance_id
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ailit_runtime.errors import RuntimeProtocolError
from ailit_runtime.trace_store import JsonlTraceStore, TraceRow


def _make_row(
    trace_id: str = "t1",
    from_agent: str = "a",
    to_agent: str = "",
    event_type: str = "req",
    payload: dict | None = None,
    timestamp: str = "ts",
    chat_id: str = "",
    broker_id: str = "",
    namespace: str = "",
    goal_id: str = "",
    **extra: str,
) -> TraceRow:
    data: dict = {
        "trace_id": trace_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "event_type": event_type,
        "payload": payload or {},
        "timestamp": timestamp,
        "chat_id": chat_id,
        "broker_id": broker_id,
        "namespace": namespace,
        "goal_id": goal_id,
    }
    data.update(extra)
    return TraceRow(data=data)


class TestTraceRow:
    def test_fields(self) -> None:
        row = _make_row(trace_id="t1", from_agent="agent_a", event_type="request",
                        payload={"msg": "hello"}, timestamp="2025-01-01T00:00:00Z")
        assert row.data["trace_id"] == "t1"
        assert row.data["from_agent"] == "agent_a"
        assert row.data["event_type"] == "request"
        assert row.data["payload"] == {"msg": "hello"}
        assert row.data["timestamp"] == "2025-01-01T00:00:00Z"

    def test_to_json_line(self) -> None:
        row = _make_row(trace_id="t1", from_agent="a", event_type="req",
                        payload={"x": 1}, timestamp="ts")
        line = row.to_json_line()
        parsed = json.loads(line)
        assert parsed["trace_id"] == "t1"
        assert parsed["payload"] == {"x": 1}


class TestJsonlTraceStore:
    def test_append_and_iter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            row = _make_row(trace_id="t1", from_agent="agent_a", event_type="request",
                            payload={"msg": "hello"}, timestamp="2025-01-01T00:00:00Z")
            store.append(row)
            rows = list(store.iter_rows())
            assert len(rows) == 1
            assert rows[0].data["trace_id"] == "t1"
            assert rows[0].data["payload"] == {"msg": "hello"}

    def test_iter_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            rows = list(store.iter_rows())
            assert rows == []

    def test_iter_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.jsonl"
            store = JsonlTraceStore(path=path)
            rows = list(store.iter_rows())
            assert rows == []

    def test_append_many(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            rows = [
                _make_row(trace_id="t1", from_agent="a", event_type="req", timestamp="ts1"),
                _make_row(trace_id="t2", from_agent="b", event_type="resp", timestamp="ts2"),
            ]
            n = store.append_many(rows)
            assert n == 2
            all_rows = list(store.iter_rows())
            assert len(all_rows) == 2

    def test_filter_by_chat_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            store.append(_make_row(trace_id="t1", from_agent="a", chat_id="c1", timestamp="ts1"))
            store.append(_make_row(trace_id="t2", from_agent="b", chat_id="c2", timestamp="ts2"))
            filtered = list(store.filter_rows(chat_id="c1"))
            assert len(filtered) == 1
            assert filtered[0].data["trace_id"] == "t1"

    def test_filter_by_broker_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            store.append(_make_row(trace_id="t1", from_agent="a", broker_id="b1", timestamp="ts1"))
            store.append(_make_row(trace_id="t2", from_agent="b", broker_id="b2", timestamp="ts2"))
            filtered = list(store.filter_rows(broker_id="b1"))
            assert len(filtered) == 1
            assert filtered[0].data["trace_id"] == "t1"

    def test_filter_by_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            store.append(_make_row(trace_id="t1", from_agent="a", namespace="ns1", timestamp="ts1"))
            store.append(_make_row(trace_id="t2", from_agent="b", namespace="ns2", timestamp="ts2"))
            filtered = list(store.filter_rows(namespace="ns1"))
            assert len(filtered) == 1
            assert filtered[0].data["trace_id"] == "t1"

    def test_filter_by_goal_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            store.append(_make_row(trace_id="t1", from_agent="a", goal_id="g1", timestamp="ts1"))
            store.append(_make_row(trace_id="t2", from_agent="b", goal_id="g2", timestamp="ts2"))
            filtered = list(store.filter_rows(goal_id="g1"))
            assert len(filtered) == 1
            assert filtered[0].data["trace_id"] == "t1"

    def test_filter_by_trace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            store.append(_make_row(trace_id="t1", from_agent="a", timestamp="ts1"))
            store.append(_make_row(trace_id="t2", from_agent="b", timestamp="ts2"))
            filtered = list(store.filter_rows(trace_id="t1"))
            assert len(filtered) == 1
            assert filtered[0].data["trace_id"] == "t1"

    def test_filter_by_agent_instance_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            # agent_instance_id matches from_agent
            store.append(_make_row(trace_id="t1", from_agent="agent_x", to_agent="", timestamp="ts1"))
            # agent_instance_id matches to_agent
            store.append(_make_row(trace_id="t2", from_agent="", to_agent="agent_x", timestamp="ts2"))
            # no match
            store.append(_make_row(trace_id="t3", from_agent="other", to_agent="", timestamp="ts3"))
            filtered = list(store.filter_rows(agent_instance_id="agent_x"))
            assert len(filtered) == 2
            assert {r.data["trace_id"] for r in filtered} == {"t1", "t2"}

    def test_filter_multiple_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            store.append(_make_row(trace_id="t1", from_agent="a", chat_id="c1", namespace="ns1", timestamp="ts1"))
            store.append(_make_row(trace_id="t2", from_agent="a", chat_id="c2", namespace="ns1", timestamp="ts2"))
            store.append(_make_row(trace_id="t3", from_agent="b", chat_id="c1", namespace="ns1", timestamp="ts3"))
            filtered = list(store.filter_rows(chat_id="c1", namespace="ns1"))
            assert len(filtered) == 2
            assert {r.data["trace_id"] for r in filtered} == {"t1", "t3"}

    def test_file_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            store = JsonlTraceStore(path=path)
            store.append(_make_row(trace_id="t1", from_agent="a", event_type="req",
                                   payload={"x": 1}, timestamp="ts1"))
            # Create a new store instance pointing to same file
            store2 = JsonlTraceStore(path=path)
            rows = list(store2.iter_rows())
            assert len(rows) == 1
            assert rows[0].data["payload"] == {"x": 1}

    def test_iter_rows_decode_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            path.write_text("not json\n")
            store = JsonlTraceStore(path=path)
            with pytest.raises(RuntimeProtocolError, match="trace_decode_error"):
                list(store.iter_rows())

    def test_iter_rows_invalid_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            path.write_text('"just a string"\n')
            store = JsonlTraceStore(path=path)
            with pytest.raises(RuntimeProtocolError, match="trace_invalid_shape"):
                list(store.iter_rows())
