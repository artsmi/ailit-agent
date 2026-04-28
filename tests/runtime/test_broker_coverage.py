"""Unit tests: runtime/broker.AgentBroker (handle_request, append_trace)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.runtime.broker import AgentBroker, BrokerConfig
from agent_core.runtime.models import (
    RuntimeIdentity,
    make_request_envelope,
)


@pytest.fixture
def identity() -> RuntimeIdentity:
    return RuntimeIdentity(
        runtime_id="r1",
        chat_id="c1",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns1",
    )


@pytest.fixture
def trace_path(tmp_path: Path) -> Path:
    return tmp_path / "trace.jsonl"


@pytest.fixture
def broker(tmp_path: Path, trace_path: Path) -> AgentBroker:
    """Минимальный брокер без поднятия сокет-сервера и субпроцессов."""
    rt = tmp_path / "runtime"
    rt.mkdir()
    cfg = BrokerConfig(
        runtime_dir=rt,
        socket_path=tmp_path / "broker.sock",
        chat_id="c1",
        namespace="ns1",
        project_root=str(tmp_path / "project"),
        trace_store_path=trace_path,
    )
    return AgentBroker(cfg)


class TestAgentBroker:
    def test_broker_id(self, broker: AgentBroker) -> None:
        assert broker.broker_id == "broker-c1"

    def test_append_trace_writes_file(
        self, broker: AgentBroker, trace_path: Path
    ) -> None:
        broker.append_trace({"k": 1, "v": 2})
        data = trace_path.read_text(encoding="utf-8")
        assert '"k":1' in data

    def test_handle_request_unknown_type(
        self,
        broker: AgentBroker,
        identity: RuntimeIdentity,
    ) -> None:
        env = make_request_envelope(
            identity=identity,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent="b",
            msg_type="not.a.known.type",
            payload={},
        )
        resp = broker.handle_request(env)
        assert resp.ok is False
        err = dict(resp.error or {})
        assert err.get("code") == "unknown_type"
