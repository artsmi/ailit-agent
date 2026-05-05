from __future__ import annotations

import json
import multiprocessing
import socket
import threading
import time
from pathlib import Path

from agent_core.runtime.broker import BrokerConfig, run_broker_server
from agent_core.runtime.broker_workspace_config import BrokerWorkspaceEntry
from agent_core.runtime.models import CONTRACT_VERSION
from agent_core.runtime.paths import RuntimePaths


def _run_broker(cfg_dict: dict[str, str]) -> None:
    pr = Path(cfg_dict["project_root"]).expanduser().resolve()
    cfg = BrokerConfig(
        runtime_dir=Path(cfg_dict["runtime_dir"]),
        socket_path=Path(cfg_dict["socket_path"]),
        chat_id=cfg_dict["chat_id"],
        namespace=cfg_dict["namespace"],
        project_root=cfg_dict["project_root"],
        trace_store_path=Path(cfg_dict["trace_store_path"]),
        workspace_config_path=None,
        workspace_entries=(
            BrokerWorkspaceEntry(
                namespace=cfg_dict["namespace"],
                project_root=pr,
            ),
        ),
    )
    run_broker_server(cfg)


def _send(sock: socket.socket, obj: dict[str, object]) -> dict[str, object]:
    sock.settimeout(2.0)
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    sock.sendall(payload.encode("utf-8") + b"\n")
    data = sock.recv(1_000_000).decode("utf-8", errors="replace").strip()
    return json.loads(data) if data else {}


def _mk_env(
    *,
    chat_id: str,
    broker_id: str,
    msg_type: str,
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
        "to_agent": "AgentDummy:chat-a",
        "created_at": "2026-04-25T00:00:00Z",
        "type": msg_type,
        "payload": {"message": "hi"},
    }


def test_broker_service_request_and_trace(tmp_path: Path) -> None:
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
    sub: socket.socket | None = None
    cli: socket.socket | None = None
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not sock_path.exists():
            time.sleep(0.05)
        assert sock_path.exists()

        # Subscribe to trace.
        sub = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sub.connect(str(sock_path))
        sub.sendall(b"{\"cmd\":\"subscribe_trace\"}\n")
        got_rows: list[str] = []

        def _recv_one() -> None:
            try:
                sub.settimeout(2.0)
                data = (
                    sub.recv(1_000_000)
                    .decode("utf-8", errors="replace")
                    .strip()
                )
                if data:
                    got_rows.append(data)
            except Exception:
                return

        t = threading.Thread(target=_recv_one, daemon=True)
        t.start()

        # Send service.request.
        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cli.connect(str(sock_path))
        broker_id = "broker-chat-a"
        req = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="service.request",
        )
        resp = _send(cli, req)
        assert resp["ok"] is True
        assert resp["payload"]["echo"] == "hi"

        # Ensure subscriber receives at least the request trace row.
        t.join(timeout=2.0)
        assert got_rows
    finally:
        if cli is not None:
            try:
                cli.close()
            except OSError:
                pass
        if sub is not None:
            try:
                sub.close()
            except OSError:
                pass
        p.terminate()
        p.join(timeout=2.0)
