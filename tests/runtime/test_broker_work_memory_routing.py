from __future__ import annotations

import json
import multiprocessing
import socket
import time
from pathlib import Path

import agent_core.runtime.broker as broker_mod
from agent_core.runtime.agent_memory_result_v1 import AGENT_MEMORY_RESULT_V1
from agent_core.runtime.broker import BrokerConfig, run_broker_server
from agent_core.runtime.models import CONTRACT_VERSION
from agent_core.runtime.paths import RuntimePaths

_MEMORY_CONTINUATION_EVENT: str = "memory.query_context.continuation"
_MEMORY_INJECTED_EVENT: str = "context.memory_injected"


def _run_broker(cfg_dict: dict[str, str]) -> None:
    cfg = BrokerConfig(
        runtime_dir=Path(cfg_dict["runtime_dir"]),
        socket_path=Path(cfg_dict["socket_path"]),
        chat_id=cfg_dict["chat_id"],
        namespace=cfg_dict["namespace"],
        project_root=cfg_dict["project_root"],
        trace_store_path=Path(cfg_dict["trace_store_path"]),
    )
    run_broker_server(cfg)


def _send_once(sock_path: Path, obj: dict[str, object]) -> dict[str, object]:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        sock.connect(str(sock_path))
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        sock.sendall(payload.encode("utf-8") + b"\n")
        data = sock.recv(1_000_000).decode("utf-8", errors="replace").strip()
        return json.loads(data) if data else {}
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _trace_rows(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.exists():
        return []
    out: list[dict[str, object]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _w14_trace_contract_ok(
    rows: list[dict[str, object]],
    *,
    chat_id: str,
) -> bool:
    """W14: AW→AM, ответ с agent_memory_result; inject или continuation."""
    aw = f"AgentWork:{chat_id}"
    am = "AgentMemory:global"
    action_ok_idx: int | None = None
    for i, row in enumerate(rows):
        if (
            row.get("type") == "action.start"
            and row.get("ok") is True
            and row.get("from_agent") == aw
        ):
            action_ok_idx = i
            break
    if action_ok_idx is None:
        return False
    req_idx: int | None = None
    for i in range(action_ok_idx + 1, len(rows)):
        row = rows[i]
        pl = row.get("payload")
        if not isinstance(pl, dict):
            continue
        if (
            row.get("type") == "service.request"
            and row.get("from_agent") == aw
            and row.get("to_agent") == am
            and pl.get("service") == "memory.query_context"
        ):
            req_idx = i
            break
    if req_idx is None:
        return False
    resp_idx: int | None = None
    for i in range(req_idx + 1, len(rows)):
        row = rows[i]
        if row.get("ok") is not True:
            continue
        if row.get("from_agent") != am or row.get("to_agent") != aw:
            continue
        pl = row.get("payload")
        if not isinstance(pl, dict):
            continue
        amr = pl.get("agent_memory_result")
        if not isinstance(amr, dict):
            continue
        if amr.get("schema_version") != AGENT_MEMORY_RESULT_V1:
            continue
        if not isinstance(pl.get("memory_slice"), dict):
            continue
        resp_idx = i
        break
    if resp_idx is None:
        return False
    start = resp_idx + 1
    tail = rows[start:]
    has_inject = any(
        r.get("type") == "topic.publish"
        and r.get("from_agent") == aw
        and isinstance(r.get("payload"), dict)
        and r["payload"].get("event_name") == _MEMORY_INJECTED_EVENT
        for r in tail
    )
    has_continuation = any(
        r.get("type") == "topic.publish"
        and r.get("from_agent") == aw
        and isinstance(r.get("payload"), dict)
        and r["payload"].get("event_name") == _MEMORY_CONTINUATION_EVENT
        for r in tail
    )
    if has_inject:
        inj = next(
            r
            for r in tail
            if r.get("type") == "topic.publish"
            and r.get("from_agent") == aw
            and isinstance(r.get("payload"), dict)
            and r["payload"].get("event_name") == _MEMORY_INJECTED_EVENT
        )
        inner = inj.get("payload")
        if not isinstance(inner, dict):
            return False
        body = inner.get("payload")
        if not isinstance(body, dict):
            return False
        if body.get("schema") != "context.memory_injected.v2":
            return False
        if body.get("usage_state") != "estimated":
            return False
        return True
    return has_continuation


def _mk_env(
    *,
    chat_id: str,
    broker_id: str,
    msg_type: str,
    to_agent: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "runtime_id": "rt-1",
        "chat_id": chat_id,
        "broker_id": broker_id,
        "trace_id": "trace-1",
        "message_id": f"m-{time.time_ns()}",
        "parent_message_id": None,
        "goal_id": "goal-1",
        "namespace": "ns",
        "from_agent": "client:test",
        "to_agent": to_agent,
        "created_at": "2026-04-25T00:00:00Z",
        "type": msg_type,
        "payload": payload,
    }


def test_broker_forwards_agent_memory_pag_events(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """AgentMemory stdout topic.publish events are appended to broker trace."""
    paths = RuntimePaths(runtime_dir=tmp_path / "rt")
    trace_path = paths.runtime_dir / "trace" / "trace-chat-mem.jsonl"
    captured: dict[str, object] = {}

    class FakeAgentProcess:
        def __init__(
            self,
            name: str,
            cmd: list[str],
            *,
            on_outbound_event: object | None = None,
        ) -> None:
            captured["name"] = name
            captured["cmd"] = cmd
            captured["on_outbound_event"] = on_outbound_event

    monkeypatch.setattr(broker_mod, "_AgentProcess", FakeAgentProcess)
    broker = broker_mod.AgentBroker(
        BrokerConfig(
            runtime_dir=paths.runtime_dir,
            socket_path=paths.broker_socket(chat_id="chat-mem"),
            chat_id="chat-mem",
            namespace="ns",
            project_root=str(tmp_path),
            trace_store_path=trace_path,
        ),
    )
    broker.spawn_memory()
    cb = captured.get("on_outbound_event")
    assert callable(cb)
    cb(
        {
            "contract_version": CONTRACT_VERSION,
            "runtime_id": "rt-1",
            "chat_id": "chat-mem",
            "broker_id": "broker-chat-mem",
            "trace_id": "tr",
            "message_id": "pag-1",
            "parent_message_id": "m0",
            "goal_id": "g",
            "namespace": "ns",
            "from_agent": "AgentMemory:global",
            "to_agent": None,
            "created_at": "2026-04-29T00:00:00Z",
            "type": "topic.publish",
            "payload": {
                "type": "topic.publish",
                "topic": "chat",
                "event_name": "pag.node.upsert",
                "payload": {
                    "kind": "pag.node.upsert",
                    "namespace": "ns",
                    "rev": 1,
                    "node": {"node_id": "C:a.py#x", "level": "C"},
                },
            },
        },
    )
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(x) for x in lines]
    assert rows[-1]["payload"]["event_name"] == "pag.node.upsert"


def test_broker_routes_memory_service_and_work_action(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "rt"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sock_path = paths.broker_socket(chat_id="chat-a")
    trace_path = runtime_dir / "trace" / "trace-chat-a.jsonl"
    cfg_dict = {
        "runtime_dir": str(runtime_dir),
        "socket_path": str(sock_path),
        "chat_id": "chat-a",
        "namespace": "ns",
        "project_root": str(tmp_path),
        "trace_store_path": str(trace_path),
    }
    p = multiprocessing.Process(target=_run_broker, args=(cfg_dict,))
    p.daemon = True
    p.start()
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not sock_path.exists():
            time.sleep(0.05)
        assert sock_path.exists()

        broker_id = "broker-chat-a"

        mem_req = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="service.request",
            to_agent="AgentMemory:global",
            payload={
                "service": "memory.query_context",
                "path": "tools/ailit/cli.py",
                "project_root": str(tmp_path),
                "goal": "find cli",
            },
        )
        mem_resp = _send_once(sock_path, mem_req)
        assert mem_resp["ok"] is True
        assert "grants" in mem_resp["payload"]
        mem_payload = mem_resp["payload"]
        assert isinstance(mem_payload, dict)
        # G13.2: invalid mock LLM JSON may return partial before recovery.
        assert isinstance(mem_payload.get("partial"), bool)
        assert mem_payload["project_refs"]
        assert mem_payload["recommended_next_step"]
        mem_slice = mem_payload["memory_slice"]
        assert isinstance(mem_slice, dict)
        assert mem_slice["kind"] == "memory_slice"
        assert mem_slice["level"] == "B"
        assert "B:tools/ailit/cli.py" in mem_slice["node_ids"]
        assert mem_slice["estimated_tokens"] > 0

        work_req = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="action.start",
            to_agent="AgentWork:chat-a",
            payload={"action": "work.handle_user_prompt", "prompt": "hi"},
        )
        work_resp = _send_once(sock_path, work_req)
        assert work_resp["ok"] is True
        assert "action_id" in work_resp["payload"]

        assert trace_path.exists()
        deadline2 = time.time() + 30.0
        seen_w14 = False
        while time.time() < deadline2 and not seen_w14:
            decoded = _trace_rows(trace_path)
            seen_w14 = _w14_trace_contract_ok(
                decoded,
                chat_id="chat-a",
            )
            if not seen_w14:
                time.sleep(0.05)
        assert seen_w14
    finally:
        p.terminate()
        p.join(timeout=2.0)
