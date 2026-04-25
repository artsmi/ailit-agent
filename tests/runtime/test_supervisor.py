from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

from agent_core.runtime.paths import RuntimePaths
from agent_core.runtime.supervisor import (
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
