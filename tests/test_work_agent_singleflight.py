"""Single-flight: второй work.handle_user_prompt отклоняется, пока первый в потоке."""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping

import pytest

from agent_core.runtime.models import RuntimeIdentity, make_request_envelope
from agent_core.runtime.subprocess_agents.work_agent import (
    AgentWorkWorker,
    WorkAgentConfig,
    _WorkChatSession,
)


def test_second_prompt_rejected_while_first_run_in_flight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    hold = threading.Event()
    started = threading.Event()

    def slow_run(
        self: _WorkChatSession,
        *,
        text: str,
        workspace: Any,
        emitter: Any,
        identity: Any,
        worker: Any,
    ) -> Mapping[str, Any]:
        started.set()
        hold.wait(timeout=10.0)
        return {"ok": True, "assistant_message_id": "asst-mock"}

    monkeypatch.setattr(_WorkChatSession, "run_user_prompt", slow_run)

    w = AgentWorkWorker(WorkAgentConfig(chat_id="c1", broker_id="b1", namespace="ns"))
    root = str(tmp_path.resolve())

    def env(*, trace_id: str, message_id: str, prompt: str) -> Any:
        ident = RuntimeIdentity(
            runtime_id="r1",
            chat_id="c1",
            broker_id="b1",
            trace_id=trace_id,
            goal_id="g1",
            namespace="ns",
        )
        return make_request_envelope(
            identity=ident,
            message_id=message_id,
            parent_message_id=None,
            from_agent="User:desktop",
            to_agent="AgentWork:c1",
            msg_type="action.start",
            payload={
                "action": "work.handle_user_prompt",
                "prompt": prompt,
                "workspace": {"project_roots": [root]},
            },
        )

    first = env(trace_id="trace-1", message_id="m1", prompt="one")
    second = env(trace_id="trace-2", message_id="m2", prompt="two")

    out1 = w.handle(first)
    assert out1.get("ok") is True, out1
    if not started.wait(timeout=2.0):
        pytest.fail("first run_user_prompt did not start")

    out2 = w.handle(second)
    assert out2.get("ok") is False
    err2 = out2.get("error")
    assert isinstance(err2, dict)
    assert err2.get("code") == "agent_busy"

    hold.set()
    time.sleep(0.15)
