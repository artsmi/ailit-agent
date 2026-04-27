"""Unit tests for runtime/broker.py — coverage of uncovered lines.

Covers:
- AgentBroker (the actual class in broker.py)
- AgentBroker.register() / unregister() / send()
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_core.runtime.broker import AgentBroker
from agent_core.runtime.errors import RuntimeProtocolError
from agent_core.runtime.models import (
    RuntimeIdentity,
    make_request_envelope,
    make_response_envelope,
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


class TestAgentBroker:
    def test_register_and_send(self, identity: RuntimeIdentity) -> None:
        broker = AgentBroker()
        handler = MagicMock()
        handler.return_value = None
        broker.register("agent_a", handler)

        env = make_request_envelope(
            identity=identity,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent="agent_a",
            msg_type="test",
            payload={},
        )
        result = broker.send(env)
        handler.assert_called_once_with(env)
        assert result is None

    def test_send_with_response(self, identity: RuntimeIdentity) -> None:
        broker = AgentBroker()
        response_env = make_response_envelope(
            request=make_request_envelope(
                identity=identity,
                message_id="m1",
                parent_message_id=None,
                from_agent="a",
                to_agent="b",
                msg_type="req",
                payload={},
            ),
            ok=True,
            payload={"result": 42},
            error=None,
        )
        handler = MagicMock()
        handler.return_value = response_env
        broker.register("agent_b", handler)

        env = make_request_envelope(
            identity=identity,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent="agent_b",
            msg_type="test",
            payload={},
        )
        result = broker.send(env)
        assert result is not None
        assert result.ok is True
        assert result.payload == {"result": 42}

    def test_send_to_unknown(self, identity: RuntimeIdentity) -> None:
        broker = AgentBroker()
        env = make_request_envelope(
            identity=identity,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent="nonexistent",
            msg_type="test",
            payload={},
        )
        with pytest.raises(RuntimeProtocolError, match="not registered"):
            broker.send(env)

    def test_register_duplicate(self) -> None:
        broker = AgentBroker()
        broker.register("agent_a", MagicMock())
        with pytest.raises(RuntimeProtocolError, match="already registered"):
            broker.register("agent_a", MagicMock())

    def test_unregister_ok(self) -> None:
        broker = AgentBroker()
        handler = MagicMock()
        broker.register("agent_a", handler)
        broker.unregister("agent_a")
        # After unregister, send should fail
        identity = RuntimeIdentity(
            runtime_id="r1", chat_id="c1", broker_id="b1",
            trace_id="t1", goal_id="g1", namespace="ns1",
        )
        env = make_request_envelope(
            identity=identity,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent="agent_a",
            msg_type="test",
            payload={},
        )
        with pytest.raises(RuntimeProtocolError, match="not registered"):
            broker.send(env)

    def test_unregister_unknown(self) -> None:
        broker = AgentBroker()
        with pytest.raises(RuntimeProtocolError, match="not registered"):
            broker.unregister("unknown")

    def test_broadcast(self, identity: RuntimeIdentity) -> None:
        broker = AgentBroker()
        handler_a = MagicMock(return_value=None)
        handler_b = MagicMock(return_value=None)
        broker.register("agent_a", handler_a)
        broker.register("agent_b", handler_b)

        env = make_request_envelope(
            identity=identity,
            message_id="m1",
            parent_message_id=None,
            from_agent="broadcaster",
            to_agent=None,
            msg_type="broadcast",
            payload={},
        )
        result = broker.send(env)
        assert result is None
        handler_a.assert_called_once_with(env)
        handler_b.assert_called_once_with(env)

    def test_broadcast_no_subscribers(self, identity: RuntimeIdentity) -> None:
        broker = AgentBroker()
        env = make_request_envelope(
            identity=identity,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent=None,
            msg_type="test",
            payload={},
        )
        result = broker.send(env)
        assert result is None
