"""G14R.1: политика memory query AgentWork (C14R.1, plan/14 W14 G14R.1)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from ailit_runtime.errors import RuntimeProtocolError
from ailit_runtime.models import (
    AGENT_WORK_MEMORY_QUERY_V1,
    parse_agent_work_memory_query_v1,
)
from agent_memory.config.agent_memory_ailit_config import (
    max_memory_queries_per_user_turn,
)
from agent_memory.contracts.agent_memory_result_v1 import (
    build_agent_memory_result_v1,
)
from ailit_cli.merged_config import load_merged_ailit_config


def _default_ok_memory_payload() -> dict[str, Any]:
    mslice = {
        "injected_text": "slice ok",
        "node_ids": [],
        "edge_ids": [],
        "level": "B",
        "reason": "t",
        "staleness": "fresh",
    }
    return {
        "memory_slice": mslice,
        "agent_memory_result": build_agent_memory_result_v1(
            query_id="stub-q",
            status="complete",
            memory_slice=mslice,
            partial=False,
            decision_summary="ok",
            recommended_next_step="",
        ),
    }


@dataclass
class _StubBroker:
    available: bool = True
    response: dict[str, Any] = field(
        default_factory=lambda: {
            "ok": True,
            "payload": _default_ok_memory_payload(),
        },
    )

    def request(
        self,
        *,
        identity: Any = None,
        parent_message_id: str = "",
        to_agent: str = "",
        payload: Any = None,
        timeout_s: float = 15.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.response


def _identity(ns: str = "ns1") -> Any:
    from ailit_runtime.models import RuntimeIdentity

    return RuntimeIdentity(
        runtime_id="r1",
        chat_id="c1",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace=ns,
    )


def _workspace(tmp_path: Any) -> Any:
    from ailit_runtime.subprocess_agents import work_agent as _wa

    Ws = _wa._Workspace  # noqa: SLF001
    return Ws(
        namespace="n",
        project_root=tmp_path,
        project_roots=(),
    )


def test_memory_query_requires_subgoal_and_stop_condition() -> None:
    """C14R.1: v1 без subgoal или с неверным stop_condition — ошибка."""
    with pytest.raises(RuntimeProtocolError) as e:
        parse_agent_work_memory_query_v1(
            {
                "schema_version": AGENT_WORK_MEMORY_QUERY_V1,
                "user_turn_id": "a",
                "query_id": "b",
                "subgoal": "",
                "expected_result_kind": "mixed",
                "project_root": "/tmp",
                "namespace": "n",
            },
        )
    assert e.value.code == "invalid_memory_query_envelope"
    with pytest.raises(RuntimeProtocolError) as e2:
        parse_agent_work_memory_query_v1(
            {
                "schema_version": AGENT_WORK_MEMORY_QUERY_V1,
                "user_turn_id": "a",
                "query_id": "b",
                "subgoal": "g",
                "expected_result_kind": "mixed",
                "project_root": "/tmp",
                "namespace": "n",
                "stop_condition": {"max_runtime_steps": 1},
            },
        )
    assert e2.value.code == "invalid_memory_query_envelope"


def test_agentwork_can_issue_multiple_memory_queries_for_one_turn() -> None:
    """C14R.1: одна user-turn — несколько query_id (два валидных v1)."""
    ut = "ut-test"
    base: dict[str, Any] = {
        "schema_version": AGENT_WORK_MEMORY_QUERY_V1,
        "user_turn_id": ut,
        "subgoal": "g",
        "expected_result_kind": "mixed",
        "project_root": "/tmp",
        "namespace": "n",
        "known_paths": [],
        "known_node_ids": [],
        "stop_condition": {
            "max_runtime_steps": 12,
            "max_llm_commands": 20,
            "must_finish_explicitly": True,
        },
    }
    a = parse_agent_work_memory_query_v1({**base, "query_id": f"mq-{ut}-1"})
    b = parse_agent_work_memory_query_v1({**base, "query_id": f"mq-{ut}-2"})
    assert a.user_turn_id == b.user_turn_id
    assert a.query_id != b.query_id


def test_agentwork_memory_query_loop_stops_at_config_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """C14R.10: при cap=1 второй _request_memory_slice сразу бюджет."""
    from ailit_runtime.subprocess_agents import work_agent as wa
    import ailit_runtime.subprocess_agents.work_agent as wam

    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001
    _WCS = wam._WorkChatSession  # noqa: SLF001

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 1}},
        },
    )
    stub = _StubBroker()
    monkeypatch.setattr(
        wa,
        "_BrokerServiceClient",
        lambda p: stub,
    )

    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:8]}"
    sess._memory_queries_in_turn = 0
    em = _RTE(
        identity=_identity(),
        parent_message_id="p1",
    )

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    wproxy = _Wpr()
    m1 = sess._request_memory_slice(  # noqa: SLF001
        text="hello",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=wproxy,
    )
    assert m1 is not None
    assert sess._memory_queries_in_turn == 1
    events2: list[str] = []

    def _epublish(*, event_type: str, payload: Any) -> None:
        events2.append(str(event_type))

    em2 = _RTE(identity=_identity(), parent_message_id="p1")
    em2.publish = _epublish  # type: ignore[assignment,method-assign]
    m2 = sess._request_memory_slice(
        text="second",
        workspace=_workspace(tmp_path),
        emitter=em2,
        identity=_identity(),
        parent_message_id="p1",
        worker=wproxy,
    )
    assert m2 is None
    assert "memory.query.budget_exceeded" in events2


def test_memory_query_timeout_emits_compact_event_on_socket_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-02: TimeoutError на сокете — memory.query.timeout, cap не растёт."""
    from ailit_runtime.subprocess_agents import work_agent as wa
    import ailit_runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"agent_memory_rpc_timeout_s": 30}},
        },
    )

    class _TimeoutClient:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            assert float(kwargs["timeout_s"]) == 30.0
            raise TimeoutError("simulated socket wait")

    monkeypatch.setattr(wa, "_BrokerServiceClient", _TimeoutClient)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001

    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:8]}"
    sess._memory_queries_in_turn = 0
    events: list[tuple[str, dict[str, Any]]] = []

    def _capture(*, event_type: str, payload: Any) -> None:
        events.append((str(event_type), dict(payload)))

    em = _RTE(identity=_identity(), parent_message_id="p1")
    em.publish = _capture  # type: ignore[assignment,method-assign]

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    m0 = sess._request_memory_slice(  # noqa: SLF001
        text="hello",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert m0 is None
    assert sess._memory_queries_in_turn == 0
    timeout_ev = [e for e in events if e[0] == "memory.query.timeout"]
    assert len(timeout_ev) == 1
    pl = timeout_ev[0][1]
    assert pl.get("code") == "runtime_timeout"
    assert pl.get("user_turn_id") == sess._user_turn_id
    assert pl.get("query_id", "").startswith("mq-")
    assert float(pl["timeout_s"]) == 30.0
    assert not any(e[0] == "context.memory_injected" for e in events)


def test_memory_query_timeout_emits_compact_on_rpc_runtime_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-02: ok:false + runtime_timeout от broker — тот же compact topic."""
    from ailit_runtime.subprocess_agents import work_agent as wa
    import ailit_runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"agent_memory_rpc_timeout_s": 99}},
        },
    )

    class _RpcTimeoutClient:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            assert float(kwargs["timeout_s"]) == 99.0
            return {
                "ok": False,
                "error": {
                    "code": "runtime_timeout",
                    "message": "agent timeout",
                },
            }

    monkeypatch.setattr(wa, "_BrokerServiceClient", _RpcTimeoutClient)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001

    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:8]}"
    sess._memory_queries_in_turn = 0
    names: list[str] = []

    def _capture(*, event_type: str, payload: Any) -> None:
        names.append(str(event_type))

    em = _RTE(identity=_identity(), parent_message_id="p1")
    em.publish = _capture  # type: ignore[assignment,method-assign]

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    m0 = sess._request_memory_slice(  # noqa: SLF001
        text="hello",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert m0 is None
    assert sess._memory_queries_in_turn == 0
    assert names == ["memory.query.timeout"]


def test_merged_config_has_max_memory_queries() -> None:
    """Статпроверка: ключ default в merged ailit (C14R.10)."""
    m = load_merged_ailit_config(None)
    n = max_memory_queries_per_user_turn(m)
    assert n >= 1
    m2: dict[str, Any] = {
        "memory": {"runtime": {"max_memory_queries_per_user_turn": 3}},
    }
    assert max_memory_queries_per_user_turn(m2) == 3
