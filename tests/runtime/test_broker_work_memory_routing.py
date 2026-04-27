from __future__ import annotations

import json
import multiprocessing
import socket
import time
from pathlib import Path

from agent_core.runtime.broker import BrokerConfig, run_broker_server
from agent_core.runtime.models import CONTRACT_VERSION
from agent_core.runtime.paths import RuntimePaths


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
            },
        )
        mem_resp = _send_once(sock_path, mem_req)
        assert mem_resp["ok"] is True
        assert "grants" in mem_resp["payload"]
        mem_payload = mem_resp["payload"]
        assert isinstance(mem_payload, dict)
        assert mem_payload["partial"] is False
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
        deadline2 = time.time() + 5.0
        seen_memory_pair = False
        while time.time() < deadline2 and not seen_memory_pair:
            rows = trace_path.read_text(encoding="utf-8").splitlines()
            decoded = [json.loads(r) for r in rows if r.strip()]
            seen_memory_pair = any(
                row.get("type") == "service.request"
                and row.get("from_agent") == "AgentWork:chat-a"
                and row.get("to_agent") == "AgentMemory:global"
                and row.get("payload", {}).get("service")
                == "memory.query_context"
                for row in decoded
            ) and any(
                row.get("type") == "service.request"
                and row.get("from_agent") == "AgentMemory:global"
                and row.get("to_agent") == "AgentWork:chat-a"
                and row.get("ok") is True
                and isinstance(row.get("payload"), dict)
                and isinstance(row["payload"].get("memory_slice"), dict)
                for row in decoded
            ) and any(
                row.get("type") == "topic.publish"
                and row.get("from_agent") == "AgentWork:chat-a"
                and row.get("payload", {}).get("event_name")
                == "context.memory_injected"
                and isinstance(
                    row.get("payload", {}).get("payload"),
                    dict,
                )
                and row["payload"]["payload"].get("usage_state")
                == "estimated"
                for row in decoded
            )
            if not seen_memory_pair:
                time.sleep(0.05)
        assert seen_memory_pair
    finally:
        p.terminate()
        p.join(timeout=2.0)
