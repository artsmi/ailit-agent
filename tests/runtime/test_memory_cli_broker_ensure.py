"""G20: auto broker через supervisor."""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from ailit_runtime.broker_json_client import (
    resolve_or_ensure_broker_socket_for_cli,
)
from ailit_runtime.errors import RuntimeProtocolError
from ailit_runtime.paths import RuntimePaths
from ailit_runtime.supervisor import run_supervisor_server, supervisor_request


def _run_sup(runtime_dir: str) -> None:
    run_supervisor_server(runtime_dir=Path(runtime_dir), broker_cmd=())


def test_resolve_or_ensure_creates_broker_when_registry_empty() -> None:
    """Пустой ``brokers`` → ``create_or_get_broker`` и готовый Unix-сокет.

    Каталог runtime короткий (``/tmp/...``): длинные ``tmp_path`` pytest
    превышают лимит ``AF_UNIX`` sun_path и broker не может bind.
    """
    import shutil
    import uuid

    short_rt = Path("/tmp") / f"ailit-brk-{uuid.uuid4().hex[:10]}"
    short_rt.mkdir(parents=True, exist_ok=True)
    proj = short_rt / "repo"
    proj.mkdir()
    proc = multiprocessing.Process(target=_run_sup, args=(str(short_rt),))
    proc.daemon = True
    proc.start()
    sup_sock = RuntimePaths(runtime_dir=short_rt).supervisor_socket
    deadline = time.time() + 8.0
    while time.time() < deadline and not sup_sock.exists():
        time.sleep(0.05)
    assert sup_sock.exists()

    lst = supervisor_request(
        socket_path=sup_sock,
        request={"cmd": "brokers"},
        timeout_s=2.0,
    )
    assert lst.get("ok") is True
    brokers0 = lst.get("result", {}).get("brokers")
    assert brokers0 == []

    sock, cid = resolve_or_ensure_broker_socket_for_cli(
        explicit_socket=None,
        runtime_dir=short_rt,
        broker_chat_id=None,
        primary_namespace="ns-ensure-test",
        primary_project_root=proj,
        allow_auto_chat_id=True,
    )
    assert sock.exists() and sock.is_socket()
    assert len(cid) <= 16
    assert cid[0] == "c"

    lst2 = supervisor_request(
        socket_path=sup_sock,
        request={"cmd": "brokers"},
        timeout_s=2.0,
    )
    rows = lst2.get("result", {}).get("brokers")
    assert isinstance(rows, list) and len(rows) >= 1

    proc.terminate()
    proc.join(timeout=3.0)
    shutil.rmtree(short_rt, ignore_errors=True)


def test_resolve_or_ensure_explicit_socket_requires_chat_id(
    tmp_path: Path,
) -> None:
    """Явный ``--broker-socket`` без ``chat_id`` — ошибка контракта."""
    sock_path = tmp_path / "broker.sock"
    sock_path.touch()
    with pytest.raises(RuntimeProtocolError) as exc_info:
        resolve_or_ensure_broker_socket_for_cli(
            explicit_socket=sock_path,
            runtime_dir=tmp_path,
            broker_chat_id=None,
            primary_namespace="ns-x",
            primary_project_root=tmp_path,
            allow_auto_chat_id=True,
        )
    assert exc_info.value.code == "missing_broker_chat_id"
