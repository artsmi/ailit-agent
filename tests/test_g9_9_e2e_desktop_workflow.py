"""E2E G9.9.1: project registry → PAG index → desktop/runtime (Workflow 9)."""

from __future__ import annotations

import json
import multiprocessing
import socket
import time
from pathlib import Path

import pytest

from ailit_runtime.models import CONTRACT_VERSION
from ailit_runtime.paths import RuntimePaths
from ailit_runtime.supervisor import (
    run_supervisor_server,
    supervisor_request,
)
from ailit_cli.cli import main


def _run_supervisor(runtime_dir: str) -> None:
    run_supervisor_server(runtime_dir=Path(runtime_dir))


def _wait_path(p: Path, *, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline and not p.exists():
        time.sleep(0.05)
    assert p.exists()


def _send_broker(
    broker_sock: Path,
    obj: dict[str, object],
) -> dict[str, object]:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(4.0)
        sock.connect(str(broker_sock))
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        sock.sendall(payload.encode("utf-8") + b"\n")
        data = sock.recv(1_000_000).decode("utf-8", errors="replace").strip()
        return json.loads(data) if data else {}
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _mk_work_prompt(chat_id: str, broker_id: str) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "runtime_id": "rt-g9-9",
        "chat_id": chat_id,
        "broker_id": broker_id,
        "trace_id": f"trace-{chat_id}",
        "message_id": f"m-{time.time_ns()}",
        "parent_message_id": None,
        "goal_id": "goal-1",
        "namespace": "ns",
        "from_agent": "client:test",
        "to_agent": f"AgentWork:{chat_id}",
        "created_at": "2026-04-25T00:00:00Z",
        "type": "action.start",
        "payload": {"action": "work.handle_user_prompt", "prompt": "e2e g9.9"},
    }


def test_g9_9_e2e_project_add_memory_index_desktop_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """add → index → `ailit desktop` без AppImage: exit 2 и подсказки."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "sample-proj"
    proj.mkdir()
    inst = tmp_path / "ailit-install"
    (inst / "desktop").mkdir(parents=True)
    monkeypatch.setenv("AILIT_INSTALL_PREFIX", str(inst))
    monkeypatch.chdir(proj)

    assert main(["project", "add"]) == 0
    capfd.readouterr()
    assert main(["memory", "index", "--project-root", str(proj)]) == 0
    out_index, _ = capfd.readouterr()
    line = [ln for ln in out_index.splitlines() if ln.strip()][0]
    payload = json.loads(line)
    assert payload.get("ok") is True
    assert str(payload.get("project_root", "")) == str(proj.resolve())

    assert main(["desktop"]) == 2
    _, err = capfd.readouterr()
    assert (
        "Desktop binary" in err
        or "бинар" in err.lower()
        or "AppImage" in err
    )
    assert "ailit desktop --dev" in err or "--dev" in err


def test_g9_9_e2e_supervisor_broker_trace_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime: supervisor → broker → append trace (совместимо с G8.8 e2e)."""
    proot = tmp_path / "p"
    proot.mkdir()
    chat_id = "g9-9"
    broker_id = "broker-g9-9"
    runtime_dir = tmp_path / "rt"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(runtime_dir))
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
                "chat_id": chat_id,
                "namespace": "ns",
                "project_root": str(proot),
            },
        )
        assert resp.get("ok") is True
        endpoint = str(resp.get("result", {}).get("endpoint", ""))
        assert endpoint.startswith("unix://")
        bpath = Path(endpoint.removeprefix("unix://"))
        _wait_path(bpath)
        work = _send_broker(bpath, _mk_work_prompt(chat_id, broker_id))
        assert work.get("ok") is True
        tr = runtime_dir / "trace" / f"trace-{chat_id}.jsonl"
        _wait_path(tr)
        rows = tr.read_text(encoding="utf-8").splitlines()
        assert rows
    finally:
        p.terminate()
        p.join(timeout=2.0)
