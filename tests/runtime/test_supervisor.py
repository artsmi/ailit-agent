from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

from ailit_runtime.paths import RuntimePaths
from ailit_runtime.supervisor import (
    run_supervisor_server,
    supervisor_request,
)


def _run_supervisor(runtime_dir: str) -> None:
    run_supervisor_server(runtime_dir=Path(runtime_dir))


def test_supervisor_create_list_stop(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "rt"
    p = multiprocessing.Process(
        target=_run_supervisor,
        args=(str(runtime_dir),),
    )
    p.daemon = True
    p.start()
    try:
        paths = RuntimePaths(runtime_dir=runtime_dir)
        sock = paths.supervisor_socket
        deadline = time.time() + 5.0
        while time.time() < deadline and not sock.exists():
            time.sleep(0.05)
        assert sock.exists()

        r1 = supervisor_request(
            socket_path=sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-a",
                "namespace": "ns",
                "project_root": "/tmp/repo",
            },
        )
        assert r1["ok"] is True
        b1 = r1["result"]
        assert b1["chat_id"] == "chat-a"

        r2 = supervisor_request(
            socket_path=sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-b",
                "namespace": "ns",
                "project_root": "/tmp/repo",
            },
        )
        assert r2["ok"] is True
        assert r2["result"]["chat_id"] == "chat-b"

        lst = supervisor_request(socket_path=sock, request={"cmd": "brokers"})
        assert lst["ok"] is True
        assert len(lst["result"]["brokers"]) == 2

        stopped = supervisor_request(
            socket_path=sock,
            request={"cmd": "stop_broker", "chat_id": "chat-a"},
        )
        assert stopped["ok"] is True
        assert stopped["result"]["state"] == "failed"
    finally:
        p.terminate()
        p.join(timeout=2.0)


def test_supervisor_create_broker_with_workspace_tc_py_sup_01(
    tmp_path: Path,
) -> None:
    """TC-PY-SUP-01: primary + workspace[1], ok и endpoint."""
    runtime_dir = tmp_path / "rt"
    primary = tmp_path / "primary"
    extra = tmp_path / "extra"
    primary.mkdir()
    extra.mkdir()
    p = multiprocessing.Process(
        target=_run_supervisor,
        args=(str(runtime_dir),),
    )
    p.daemon = True
    p.start()
    try:
        paths = RuntimePaths(runtime_dir=runtime_dir)
        sock = paths.supervisor_socket
        deadline = time.time() + 5.0
        while time.time() < deadline and not sock.exists():
            time.sleep(0.05)
        assert sock.exists()

        r1 = supervisor_request(
            socket_path=sock,
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
        assert r1["ok"] is True
        b1 = r1["result"]
        assert b1["chat_id"] == "chat-ws"
        assert b1["namespace"] == "pns"
        assert b1["primary_namespace"] == "pns"
        ws = b1.get("workspace")
        assert isinstance(ws, list) and len(ws) == 1
        assert ws[0].get("namespace") == "sns"
        ep = str(b1.get("endpoint", "") or "")
        assert ep.startswith("unix://")
    finally:
        p.terminate()
        p.join(timeout=2.0)


def test_supervisor_create_broker_legacy_tc_py_sup_02(tmp_path: Path) -> None:
    """TC-PY-SUP-02: только namespace/project_root — broker создаётся."""
    runtime_dir = tmp_path / "rt"
    p = multiprocessing.Process(
        target=_run_supervisor,
        args=(str(runtime_dir),),
    )
    p.daemon = True
    p.start()
    try:
        paths = RuntimePaths(runtime_dir=runtime_dir)
        sock = paths.supervisor_socket
        deadline = time.time() + 5.0
        while time.time() < deadline and not sock.exists():
            time.sleep(0.05)
        assert sock.exists()

        r1 = supervisor_request(
            socket_path=sock,
            request={
                "cmd": "create_or_get_broker",
                "chat_id": "chat-legacy",
                "namespace": "ns",
                "project_root": "/tmp/repo",
            },
        )
        assert r1["ok"] is True
        b1 = r1["result"]
        assert b1["namespace"] == "ns"
        assert b1.get("workspace") == []
    finally:
        p.terminate()
        p.join(timeout=2.0)
