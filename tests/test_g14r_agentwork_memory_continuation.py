"""G14R / W14: UC-01 continuation по SoT ``agent_memory_result`` (task_1_2)."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

import pytest

from agent_core.runtime.agent_memory_result_v1 import (
    build_agent_memory_result_v1,
)
from agent_core.tool_runtime.registry import ToolRegistry


def _identity(ns: str = "ns1") -> Any:
    from agent_core.runtime.models import RuntimeIdentity

    return RuntimeIdentity(
        runtime_id="r1",
        chat_id="c1",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace=ns,
    )


def _workspace(tmp_path: Any) -> Any:
    from agent_core.runtime.subprocess_agents import work_agent as _wa

    Ws = _wa._Workspace  # noqa: SLF001
    return Ws(
        namespace="n",
        project_root=tmp_path,
        project_roots=(),
    )


def _slice(injected: str) -> dict[str, Any]:
    return {
        "injected_text": injected,
        "node_ids": ["C:src/auth.py:10"],
        "edge_ids": [],
        "level": "B",
        "reason": "t",
        "staleness": "fresh",
    }


def test_uc01_partial_continuation_two_memory_queries_before_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-01 (task_1_2): partial+continuation → два memory.query_context."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    calls: list[dict[str, Any]] = []
    idx = {"i": 0}
    s1 = _slice("early partial text must not be injected alone")
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=s1,
        partial=True,
        decision_summary="p",
        recommended_next_step="Drill down into the auth module edges",
    )
    s2 = _slice("final accepted slice")
    amr2 = build_agent_memory_result_v1(
        query_id="q2",
        status="complete",
        memory_slice=s2,
        partial=False,
        decision_summary="ok",
        recommended_next_step="",
    )
    seq = (
        {
            "ok": True,
            "payload": {
                "memory_slice": s1,
                "agent_memory_result": amr1,
            },
        },
        {
            "ok": True,
            "payload": {
                "memory_slice": s2,
                "agent_memory_result": amr2,
            },
        },
    )

    class _SeqClient:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            pl = kwargs.get("payload")
            if isinstance(pl, dict):
                calls.append(dict(pl))
            i = idx["i"]
            idx["i"] += 1
            if i >= len(seq):
                return seq[-1]
            return seq[i]

    monkeypatch.setattr(wa, "_BrokerServiceClient", _SeqClient)

    def _registry_build_forbidden(
        self: Any,
        *,
        project_root: Any,
        project_roots: Any | None = None,
    ) -> Any:
        raise AssertionError(
            "UC-01: glob_file/read_file/run_shell registry must not be "
            "assembled during _request_memory_slice (memory-path only).",
        )

    monkeypatch.setattr(
        wam._RegistryAssembler,
        "build",
        _registry_build_forbidden,
    )

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001

    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:12]}"
    sess._memory_queries_in_turn = 0
    trace: list[tuple[str, dict[str, Any]]] = []

    def _cap(*, event_type: str, payload: Any) -> None:
        trace.append((str(event_type), dict(payload)))

    em = _RTE(identity=_identity(), parent_message_id="p1")
    em.publish = _cap  # type: ignore[method-assign]

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    msg = sess._request_memory_slice(
        text="explore auth",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert msg is not None
    body = str(msg.content or "")
    assert "final accepted slice" in body
    assert "early partial text" not in body
    mem_svc = [p for p in calls if p.get("service") == "memory.query_context"]
    assert len(mem_svc) == 2
    assert mem_svc[0]["query_id"] != mem_svc[1]["query_id"]
    cont = [t for t in trace if t[0] == "memory.query_context.continuation"]
    assert len(cont) == 1
    assert cont[0][1].get("reason") == wam._MEMORY_QUERY_CONTINUATION_REASON
    assert cont[0][1].get("previous_query_id") == mem_svc[0]["query_id"]
    assert cont[0][1].get("next_query_id") == mem_svc[1]["query_id"]
    inj = [t for t in trace if t[0] == "context.memory_injected"]
    assert len(inj) == 1
    inj_pl = inj[0][1]
    assert inj_pl.get("decision_summary") == "ok"
    assert inj_pl.get("recommended_next_step") == ""


def test_uc01_a2_partial_without_continuation_no_second_query_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-01 A2: partial без continuation — один ``memory.query_context``."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    calls: list[dict[str, Any]] = []
    s1 = _slice("partial without follow-up")
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=s1,
        partial=True,
        decision_summary="p",
        recommended_next_step="read selected context",
    )

    class _OneShot:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            pl = kwargs.get("payload")
            if isinstance(pl, dict):
                calls.append(dict(pl))
            return {
                "ok": True,
                "payload": {
                    "memory_slice": s1,
                    "agent_memory_result": amr1,
                },
            }

    monkeypatch.setattr(wa, "_BrokerServiceClient", _OneShot)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001
    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:12]}"
    sess._memory_queries_in_turn = 0
    em = _RTE(identity=_identity(), parent_message_id="p1")

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    msg = sess._request_memory_slice(
        text="x",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert msg is not None
    mem_svc = [p for p in calls if p.get("service") == "memory.query_context"]
    assert len(mem_svc) == 1


def test_uc01_two_memory_queries_before_orchestrator_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Порядок: оба memory RPC до первого ``WorkTaskOrchestrator.run``."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam

    monkeypatch.setenv("AILIT_WORK_MICRO_ORCHESTRATOR", "0")
    monkeypatch.setenv("AILIT_WORK_AGENT_PERM", "0")
    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    mem_n = {"v": 0}
    s1 = _slice("p1")
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=s1,
        partial=True,
        decision_summary="p",
        recommended_next_step="Resolve imports in pkg/__init__.py",
    )
    s2 = _slice("done")
    amr2 = build_agent_memory_result_v1(
        query_id="q2",
        status="complete",
        memory_slice=s2,
        partial=False,
        decision_summary="ok",
        recommended_next_step="",
    )
    seq = (
        {
            "ok": True,
            "payload": {
                "memory_slice": s1,
                "agent_memory_result": amr1,
            },
        },
        {
            "ok": True,
            "payload": {
                "memory_slice": s2,
                "agent_memory_result": amr2,
            },
        },
    )
    i = {"k": 0}

    class _SeqClient:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            mem_n["v"] += 1
            k = i["k"]
            i["k"] += 1
            return seq[min(k, len(seq) - 1)]

    monkeypatch.setattr(wa, "_BrokerServiceClient", _SeqClient)

    _SUBSTITUTE_TOOLS = ("glob_file", "read_file", "run_shell")
    _orig_reg_build = wam._RegistryAssembler.build
    _mem_at_registry_build: list[int] = []

    def _reg_build_track(
        self: Any,
        *,
        project_root: Any,
        project_roots: Any | None = None,
    ) -> Any:
        assert mem_n["v"] >= 2, (
            "UC-01: memory.query_context must complete (>=2 RPCs) before "
            "tool registry (glob_file/read_file/run_shell) is assembled."
        )
        _mem_at_registry_build.append(int(mem_n["v"]))
        reg = _orig_reg_build(
            self,
            project_root=project_root,
            project_roots=project_roots,
        )

        def _wrap_handler(name: str, inner: Any) -> Any:
            def _h(args: Mapping[str, Any]) -> str:
                assert mem_n["v"] >= 2, (
                    f"UC-01: {name} must not run before memory-path complete "
                    f"(memory RPC count={mem_n['v']})."
                )
                return inner(args)

            return _h

        handlers = dict(reg.handlers)
        for tn in _SUBSTITUTE_TOOLS:
            if tn in handlers:
                handlers[tn] = _wrap_handler(tn, handlers[tn])

        return ToolRegistry(specs=dict(reg.specs), handlers=handlers)

    monkeypatch.setattr(wam._RegistryAssembler, "build", _reg_build_track)

    orch = wam.WorkTaskOrchestrator
    orig_run = orch.run

    def _wrapped_run(self: Any, request: Any) -> Any:
        assert mem_n["v"] >= 2, (
            "memory-path must finish before tools/orchestrator"
        )
        return orig_run(self, request)

    monkeypatch.setattr(orch, "run", _wrapped_run)

    worker = wa.AgentWorkWorker(
        wa.WorkAgentConfig(
            chat_id="c-orch",
            broker_id="b1",
            namespace="ns",
            broker_socket_path="/x",
        ),
    )
    emitter = wam._RuntimeEventEmitter(
        identity=_identity(ns="ns"),
        parent_message_id="mid-1",
    )
    worker._session.run_user_prompt(
        text="hi",
        workspace=_workspace(tmp_path),
        emitter=emitter,
        identity=_identity(ns="ns"),
        worker=worker,
    )
    assert _mem_at_registry_build == [2]


def test_agentwork_uc02_legacy_envelope_after_canonicalization_no_spurious_continuation(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-02: partial + агрессивный rns без mcr/роста refs — один RPC."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    calls: list[dict[str, Any]] = []
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=None,
        partial=True,
        decision_summary="p",
        recommended_next_step="Drill down into every module aggressively",
        explicit_results=[],
        explicit_status="partial",
    )
    s1 = _slice("legacy partial body")

    class _OneShot:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            pl = kwargs.get("payload")
            if isinstance(pl, dict):
                calls.append(dict(pl))
            return {
                "ok": True,
                "payload": {
                    "memory_slice": s1,
                    "agent_memory_result": amr1,
                },
            }

    monkeypatch.setattr(wa, "_BrokerServiceClient", _OneShot)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001
    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:12]}"
    sess._memory_queries_in_turn = 0
    em = _RTE(identity=_identity(), parent_message_id="p1")

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    msg = sess._request_memory_slice(
        text="x",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert msg is not None
    mem_svc = [p for p in calls if p.get("service") == "memory.query_context"]
    assert len(mem_svc) == 1


def test_agentwork_uc03_fix_memory_llm_json_terminal_no_second_memory_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-03: ``fix_memory_llm_json`` — терминально для memory-loop."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam
    from agent_core.runtime.agent_memory_result_v1 import (
        FIX_MEMORY_LLM_JSON_STEP,
    )

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    calls: list[dict[str, Any]] = []
    s1 = _slice("slice with telemetry")
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=s1,
        partial=True,
        decision_summary="p",
        recommended_next_step=FIX_MEMORY_LLM_JSON_STEP,
    )

    class _OneShot:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            pl = kwargs.get("payload")
            if isinstance(pl, dict):
                calls.append(dict(pl))
            return {
                "ok": True,
                "payload": {
                    "memory_slice": s1,
                    "agent_memory_result": amr1,
                },
            }

    monkeypatch.setattr(wa, "_BrokerServiceClient", _OneShot)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001
    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:12]}"
    sess._memory_queries_in_turn = 0
    em = _RTE(identity=_identity(), parent_message_id="p1")

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    msg = sess._request_memory_slice(
        text="x",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert msg is not None
    mem_svc = [p for p in calls if p.get("service") == "memory.query_context"]
    assert len(mem_svc) == 1


def test_agentwork_uc03_w14_contract_failure_terminal_no_second_memory_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-03: ``w14_contract_failure`` на слайсе — без второго RPC."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    calls: list[dict[str, Any]] = []
    s1 = {
        "injected_text": "w14 body",
        "node_ids": ["C:x.py:1"],
        "edge_ids": [],
        "level": "B",
        "reason": "t",
        "staleness": "fresh",
        "w14_contract_failure": True,
    }
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=s1,
        partial=True,
        decision_summary="p",
        recommended_next_step="retry",
    )

    class _OneShot:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            pl = kwargs.get("payload")
            if isinstance(pl, dict):
                calls.append(dict(pl))
            return {
                "ok": True,
                "payload": {
                    "memory_slice": s1,
                    "agent_memory_result": amr1,
                },
            }

    monkeypatch.setattr(wa, "_BrokerServiceClient", _OneShot)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001
    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:12]}"
    sess._memory_queries_in_turn = 0
    em = _RTE(identity=_identity(), parent_message_id="p1")

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    msg = sess._request_memory_slice(
        text="x",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert msg is not None
    mem_svc = [p for p in calls if p.get("service") == "memory.query_context"]
    assert len(mem_svc) == 1


def test_agentwork_uc04_second_memory_query_only_on_graph_progress_or_explicit_continuation(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-04: без новых refs/mcr третий RPC не делаем (финиш на 2-м ответе)."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    calls: list[dict[str, Any]] = []
    idx = {"i": 0}
    s1 = _slice("first partial")
    s2 = _slice("second partial same graph")
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=s1,
        partial=True,
        decision_summary="p1",
        recommended_next_step="More context on auth",
    )
    amr2 = build_agent_memory_result_v1(
        query_id="q2",
        status="partial",
        memory_slice=s2,
        partial=True,
        decision_summary="p2",
        recommended_next_step="Still more on auth",
    )
    seq = (
        {
            "ok": True,
            "payload": {
                "memory_slice": s1,
                "agent_memory_result": amr1,
            },
        },
        {
            "ok": True,
            "payload": {
                "memory_slice": s2,
                "agent_memory_result": amr2,
            },
        },
    )

    class _SeqClient:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            pl = kwargs.get("payload")
            if isinstance(pl, dict):
                calls.append(dict(pl))
            i = idx["i"]
            idx["i"] += 1
            if i >= len(seq):
                return seq[-1]
            return seq[i]

    monkeypatch.setattr(wa, "_BrokerServiceClient", _SeqClient)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001
    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:12]}"
    sess._memory_queries_in_turn = 0
    em = _RTE(identity=_identity(), parent_message_id="p1")

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    msg = sess._request_memory_slice(
        text="explore auth",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert msg is not None
    body = str(msg.content or "")
    assert "second partial same graph" in body
    assert "first partial" not in body
    mem_svc = [p for p in calls if p.get("service") == "memory.query_context"]
    assert len(mem_svc) == 2


def test_agentwork_uc04_memory_continuation_required_allows_second_without_new_refs(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """UC-04: ``memory_continuation_required`` — второй RPC без новых refs."""
    from agent_core.runtime.subprocess_agents import work_agent as wa
    import agent_core.runtime.subprocess_agents.work_agent as wam

    monkeypatch.setattr(
        wa,
        "load_merged_ailit_config_for_memory",
        lambda: {
            "memory": {"runtime": {"max_memory_queries_per_user_turn": 8}},
        },
    )
    calls: list[dict[str, Any]] = []
    idx = {"i": 0}
    s1 = _slice("mcr partial")
    s2 = _slice("final")
    amr1 = build_agent_memory_result_v1(
        query_id="q1",
        status="partial",
        memory_slice=s1,
        partial=True,
        decision_summary="p",
        recommended_next_step="",
        memory_continuation_required=True,
    )
    amr2 = build_agent_memory_result_v1(
        query_id="q2",
        status="complete",
        memory_slice=s2,
        partial=False,
        decision_summary="ok",
        recommended_next_step="",
    )
    seq = (
        {
            "ok": True,
            "payload": {
                "memory_slice": s1,
                "agent_memory_result": amr1,
            },
        },
        {
            "ok": True,
            "payload": {
                "memory_slice": s2,
                "agent_memory_result": amr2,
            },
        },
    )

    class _SeqClient:
        def __init__(self, _p: str) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

        def request(self, **kwargs: Any) -> dict[str, Any]:
            pl = kwargs.get("payload")
            if isinstance(pl, dict):
                calls.append(dict(pl))
            i = idx["i"]
            idx["i"] += 1
            return seq[min(i, len(seq) - 1)]

    monkeypatch.setattr(wa, "_BrokerServiceClient", _SeqClient)

    _WCS = wam._WorkChatSession  # noqa: SLF001
    _RTE = wam._RuntimeEventEmitter  # noqa: SLF001
    sess = _WCS()
    sess._user_turn_id = f"ut-{uuid.uuid4().hex[:12]}"
    sess._memory_queries_in_turn = 0
    em = _RTE(identity=_identity(), parent_message_id="p1")

    class _Cfg:
        broker_socket_path: str = "/x"

    class _Wpr:
        _cfg = _Cfg()

    msg = sess._request_memory_slice(
        text="x",
        workspace=_workspace(tmp_path),
        emitter=em,
        identity=_identity(),
        parent_message_id="p1",
        worker=_Wpr(),
    )
    assert msg is not None
    mem_svc = [p for p in calls if p.get("service") == "memory.query_context"]
    assert len(mem_svc) == 2
