"""UC-05: cooperative cancel + инвариант trace (architecture §5).

Продюсеры assistant.final / action.completed с user_turn_id; терминальные
cancel-события: work_agent (run_user_prompt, _run).
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from agent_core.runtime.broker import BrokerConfig, run_broker_server
from agent_core.runtime.models import CONTRACT_VERSION
from agent_core.runtime.paths import RuntimePaths


def _run_broker_server_cfg(cfg: BrokerConfig) -> None:
    run_broker_server(cfg)


def _run_broker_with_hold(cfg_dict: dict[str, str], hold_s: str) -> None:
    os.environ["AILIT_TEST_MEMORY_PIPELINE_HOLD_S"] = hold_s
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
    import socket

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(60.0)
        sock.connect(str(sock_path))
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        sock.sendall(payload.encode("utf-8") + b"\n")
        data = sock.recv(2_000_000).decode("utf-8", errors="replace").strip()
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
        "created_at": "2026-05-01T00:00:00Z",
        "type": msg_type,
        "payload": payload,
    }


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


def _topic_event_name(row: dict[str, object]) -> str:
    pl = row.get("payload")
    if not isinstance(pl, dict):
        return ""
    return str(pl.get("event_name") or "")


def _topic_inner(row: dict[str, object]) -> dict[str, object]:
    pl = row.get("payload")
    if not isinstance(pl, dict):
        return {}
    inner = pl.get("payload")
    return inner if isinstance(inner, dict) else {}


def _extract_user_turn_id(rows: list[dict[str, object]], chat_id: str) -> str:
    aw = f"AgentWork:{chat_id}"
    for row in rows:
        if row.get("type") != "topic.publish":
            continue
        if row.get("from_agent") != aw:
            continue
        if _topic_event_name(row) != "action.started":
            continue
        ut = str(_topic_inner(row).get("user_turn_id") or "").strip()
        if ut:
            return ut
    return ""


def _assert_uc05_no_zombie_final_after_cancel(
    rows: list[dict[str, object]],
    *,
    chat_id: str,
) -> None:
    """T_cancel: первый cancel; после него нет zombie final/completed."""
    aw = f"AgentWork:{chat_id}"
    cancel_idx: int | None = None
    cancel_ut = ""
    for i, row in enumerate(rows):
        if row.get("type") != "topic.publish":
            continue
        if row.get("from_agent") != aw:
            continue
        en = _topic_event_name(row)
        if en not in ("session.cancelled", "action.cancelled"):
            continue
        ut = str(_topic_inner(row).get("user_turn_id") or "").strip()
        if ut:
            cancel_idx = i
            cancel_ut = ut
            break
    assert cancel_idx is not None, (
        "expected session.cancelled or action.cancelled"
    )
    tail = rows[(cancel_idx + 1):]
    for row in tail:
        if row.get("type") != "topic.publish" or row.get("from_agent") != aw:
            continue
        en = _topic_event_name(row)
        if en not in ("assistant.final", "action.completed"):
            continue
        ut2 = str(_topic_inner(row).get("user_turn_id") or "").strip()
        if ut2 == cancel_ut:
            msg = f"zombie {en} after cancel for user_turn_id={cancel_ut!r}"
            pytest.fail(msg)


def test_w14_uc05_cancel_during_memory_query_no_zombie_final_or_completed(
    tmp_path: Path,
) -> None:
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
    prev_hold = os.environ.get("AILIT_TEST_MEMORY_PIPELINE_HOLD_S")
    p = multiprocessing.Process(
        target=_run_broker_with_hold,
        args=(cfg_dict, "1.5"),
    )
    p.daemon = True
    p.start()
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline and not sock_path.exists():
            time.sleep(0.05)
        assert sock_path.exists()
        broker_id = "broker-chat-a"
        work_req = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="action.start",
            to_agent="AgentWork:chat-a",
            payload={
                "action": "work.handle_user_prompt",
                "prompt": "memory cancel uc05",
                "workspace": {"project_roots": [str(tmp_path)]},
            },
        )
        work_resp = _send_once(sock_path, work_req)
        assert work_resp.get("ok") is True
        ut = ""
        for _ in range(200):
            ut = _extract_user_turn_id(_trace_rows(trace_path), "chat-a")
            if ut:
                break
            time.sleep(0.05)
        assert ut, "user_turn_id not found in trace"
        cancel_req = _mk_env(
            chat_id="chat-a",
            broker_id=broker_id,
            msg_type="service.request",
            to_agent="AgentWork:chat-a",
            payload={
                "action": "runtime.cancel_active_turn",
                "chat_id": "chat-a",
                "user_turn_id": ut,
            },
        )
        cancel_resp = _send_once(sock_path, cancel_req)
        assert cancel_resp.get("ok") is True
        deadline2 = time.time() + 45.0
        term = ("session.cancelled", "action.cancelled")
        while time.time() < deadline2:
            rows = _trace_rows(trace_path)
            has_cancel = any(
                r.get("type") == "topic.publish"
                and r.get("from_agent") == "AgentWork:chat-a"
                and _topic_event_name(r) in term
                for r in rows
            )
            if has_cancel:
                _assert_uc05_no_zombie_final_after_cancel(
                    rows,
                    chat_id="chat-a",
                )
                return
            time.sleep(0.08)
        pytest.fail("timeout waiting for cancel terminal events")
    finally:
        p.terminate()
        p.join(timeout=5.0)
        if prev_hold is None:
            os.environ.pop("AILIT_TEST_MEMORY_PIPELINE_HOLD_S", None)
        else:
            os.environ["AILIT_TEST_MEMORY_PIPELINE_HOLD_S"] = prev_hold


def test_w14_uc05_cancel_before_memory_returns_without_hang(
    tmp_path: Path,
) -> None:
    """A1: отмена до memory RPC — без action.completed для того же turn."""
    runtime_dir = tmp_path / "rt2"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sock_path = paths.broker_socket(chat_id="chat-b")
    trace_path = runtime_dir / "trace" / "trace-chat-b.jsonl"
    cfg = BrokerConfig(
        runtime_dir=runtime_dir,
        socket_path=sock_path,
        chat_id="chat-b",
        namespace="ns",
        project_root=str(tmp_path),
        trace_store_path=trace_path,
    )
    p = multiprocessing.Process(
        target=_run_broker_server_cfg,
        args=(cfg,),
    )
    p.daemon = True
    p.start()
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline and not sock_path.exists():
            time.sleep(0.05)
        assert sock_path.exists()
        broker_id = "broker-chat-b"
        work_req = _mk_env(
            chat_id="chat-b",
            broker_id=broker_id,
            msg_type="action.start",
            to_agent="AgentWork:chat-b",
            payload={
                "action": "work.handle_user_prompt",
                "prompt": "quick",
                "workspace": {"project_roots": [str(tmp_path)]},
            },
        )
        _send_once(sock_path, work_req)
        ut = ""
        for _ in range(150):
            ut = _extract_user_turn_id(_trace_rows(trace_path), "chat-b")
            if ut:
                break
            time.sleep(0.03)
        assert ut
        cancel_req = _mk_env(
            chat_id="chat-b",
            broker_id=broker_id,
            msg_type="service.request",
            to_agent="AgentWork:chat-b",
            payload={
                "action": "runtime.cancel_active_turn",
                "chat_id": "chat-b",
                "user_turn_id": ut,
            },
        )
        cr = _send_once(sock_path, cancel_req)
        assert cr.get("ok") is True
        time.sleep(0.6)
        rows = _trace_rows(trace_path)
        bad = [
            r
            for r in rows
            if r.get("type") == "topic.publish"
            and r.get("from_agent") == "AgentWork:chat-b"
            and _topic_event_name(r) == "action.completed"
            and str(_topic_inner(r).get("user_turn_id") or "") == ut
        ]
        assert not bad
    finally:
        p.terminate()
        p.join(timeout=5.0)
