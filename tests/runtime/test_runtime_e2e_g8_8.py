from __future__ import annotations

import json
import multiprocessing
import socket
import time
from pathlib import Path

from ailit_runtime.models import CONTRACT_VERSION
from ailit_runtime.paths import RuntimePaths
from ailit_runtime.supervisor import (
    run_supervisor_server,
    supervisor_request,
)


def _run_supervisor(runtime_dir: str) -> None:
    run_supervisor_server(runtime_dir=Path(runtime_dir))


def _wait_path(p: Path, *, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline and not p.exists():
        time.sleep(0.05)
    assert p.exists()


def _send_once(sock_path: Path, obj: dict[str, object]) -> dict[str, object]:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        sock.connect(str(sock_path))
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        sock.sendall(payload.encode("utf-8") + b"\n")
        data = sock.recv(1_000_000).decode("utf-8", errors="replace").strip()
        out = json.loads(data) if data else {}
        return out if isinstance(out, dict) else {}
    finally:
        try:
            sock.close()
        except OSError:
            pass


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
        "runtime_id": "rt-test",
        "chat_id": chat_id,
        "broker_id": broker_id,
        "trace_id": f"trace-{chat_id}",
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


def test_e2e_one_chat_work_and_memory(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "rt"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sup_sock = paths.supervisor_socket

    p = multiprocessing.Process(
        target=_run_supervisor,
        args=(str(runtime_dir),),
    )
    p.daemon = True
    p.start()
    try:
        _wait_path(sup_sock)
        resp = supervisor_request(
            socket_path=sup_sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-a",
                "namespace": "ns",
                "project_root": str(tmp_path),
            },
        )
        assert resp["ok"] is True
        endpoint = str(resp["result"]["endpoint"])
        assert endpoint.startswith("unix://")
        broker_sock = Path(endpoint[len("unix://"):])
        _wait_path(broker_sock)

        broker_id = "broker-chat-a"
        mem_req = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="service.request",
            to_agent="AgentMemory:chat-a",
            payload={
                "service": "memory.query_context",
                "path": "ailit/ailit_cli/cli.py",
            },
        )
        mem_resp = _send_once(broker_sock, mem_req)
        assert mem_resp["ok"] is True

        work_req = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="action.start",
            to_agent="AgentWork:chat-a",
            payload={"action": "work.handle_user_prompt", "prompt": "hi"},
        )
        work_resp = _send_once(broker_sock, work_req)
        assert work_resp["ok"] is True

        trace = runtime_dir / "trace" / "trace-chat-a.jsonl"
        _wait_path(trace)
        rows = trace.read_text(encoding="utf-8").splitlines()
        assert rows
    finally:
        p.terminate()
        p.join(timeout=2.0)


def test_e2e_multiple_chats_and_restart_broker(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "rt"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sup_sock = paths.supervisor_socket

    p = multiprocessing.Process(
        target=_run_supervisor,
        args=(str(runtime_dir),),
    )
    p.daemon = True
    p.start()
    try:
        _wait_path(sup_sock)
        a = supervisor_request(
            socket_path=sup_sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-a",
                "namespace": "ns",
                "project_root": str(tmp_path),
            },
        )
        b = supervisor_request(
            socket_path=sup_sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-b",
                "namespace": "ns",
                "project_root": str(tmp_path),
            },
        )
        assert a["ok"] is True and b["ok"] is True
        assert a["result"]["endpoint"] != b["result"]["endpoint"]

        stopped = supervisor_request(
            socket_path=sup_sock,
            request={"cmd": "stop_broker", "chat_id": "chat-a"},
        )
        assert stopped["ok"] is True

        restarted = supervisor_request(
            socket_path=sup_sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-a",
                "namespace": "ns",
                "project_root": str(tmp_path),
            },
        )
        assert restarted["ok"] is True
        assert restarted["result"]["state"] == "running"
    finally:
        p.terminate()
        p.join(timeout=2.0)


def test_e2e_one_to_many_topic_publish_readiness(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "rt"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sup_sock = paths.supervisor_socket

    p = multiprocessing.Process(
        target=_run_supervisor,
        args=(str(runtime_dir),),
    )
    p.daemon = True
    p.start()
    try:
        _wait_path(sup_sock)
        resp = supervisor_request(
            socket_path=sup_sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-a",
                "namespace": "ns",
                "project_root": str(tmp_path),
            },
        )
        assert resp["ok"] is True
        endpoint = str(resp["result"]["endpoint"])
        broker_sock = Path(endpoint[len("unix://"):])
        _wait_path(broker_sock)

        broker_id = "broker-chat-a"
        pub = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="topic.publish",
            to_agent="",
            payload={
                "topic": "goal.started",
                "event_name": "goal.started",
            },
        )
        out = _send_once(broker_sock, pub)
        assert out["ok"] is True
    finally:
        p.terminate()
        p.join(timeout=2.0)


def test_e2e_broker_with_workspace_memory_alive(tmp_path: Path) -> None:
    """TC-PY-SUP-01: create_or_get_broker с workspace, broker отвечает."""
    runtime_dir = tmp_path / "rt"
    primary = tmp_path / "p"
    extra = tmp_path / "e"
    primary.mkdir()
    extra.mkdir()
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sup_sock = paths.supervisor_socket

    p = multiprocessing.Process(
        target=_run_supervisor,
        args=(str(runtime_dir),),
    )
    p.daemon = True
    p.start()
    try:
        _wait_path(sup_sock)
        resp = supervisor_request(
            socket_path=sup_sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-ws",
                "primary_namespace": "pns",
                "primary_project_root": str(primary.resolve()),
                "workspace": [
                    {
                        "namespace": "sns",
                        "project_root": str(extra.resolve()),
                    },
                ],
            },
        )
        assert resp["ok"] is True
        result = resp["result"]
        assert isinstance(result, dict)
        assert len(result.get("workspace") or []) == 1
        endpoint = str(result["endpoint"])
        assert endpoint.startswith("unix://")
        broker_sock = Path(endpoint[len("unix://"):])
        _wait_path(broker_sock)

        broker_id = "broker-chat-ws"
        mem_req = _mk_env(
            chat_id="chat-ws",
            broker_id=broker_id,
            msg_type="service.request",
            to_agent="AgentMemory:chat-ws",
            payload={
                "service": "memory.query_context",
                "path": "x.py",
            },
        )
        mem_resp = _send_once(broker_sock, mem_req)
        assert mem_resp["ok"] is True
    finally:
        p.terminate()
        p.join(timeout=2.0)
