"""G20.4: ``memory.index_project`` через реальный broker + AgentMemory."""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

from agent_memory.sqlite_pag import SqlitePagStore
from ailit_runtime.broker import BrokerConfig, run_broker_server
from ailit_runtime.broker_json_client import BrokerJsonRpcClient
from ailit_runtime.broker_workspace_config import BrokerWorkspaceEntry
from ailit_runtime.models import (
    RuntimeIdentity,
    RuntimeNow,
    make_request_envelope,
)
from ailit_runtime.paths import RuntimePaths


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


def test_memory_index_project_via_broker_writes_pag(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """RPC ``memory.index_project`` пишет sqlite PAG."""
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(tmp_path / "pag.sqlite3"))
    proj = tmp_path / "repo"
    proj.mkdir()
    (proj / "mod.py").write_text("ANSWER = 42\n", encoding="utf-8")

    runtime_dir = tmp_path / "rt"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sock_path = paths.broker_socket(chat_id="chat-idx-g20")
    trace_path = runtime_dir / "trace" / "trace-chat-idx-g20.jsonl"
    cfg_dict = {
        "runtime_dir": str(runtime_dir),
        "socket_path": str(sock_path),
        "chat_id": "chat-idx-g20",
        "namespace": "ns-g20",
        "project_root": str(proj),
        "trace_store_path": str(trace_path),
    }
    proc = multiprocessing.Process(target=_run_broker, args=(cfg_dict,))
    proc.daemon = True
    proc.start()
    try:
        deadline = time.time() + 8.0
        while time.time() < deadline and not sock_path.exists():
            time.sleep(0.05)
        assert sock_path.exists()

        cid = "chat-idx-g20"
        sid = "g20test01"
        identity = RuntimeIdentity(
            runtime_id=f"rt-{sid}",
            chat_id=cid,
            broker_id=f"broker-{cid}",
            trace_id=f"tr-{sid}",
            goal_id="memory_index",
            namespace="ns-g20",
        )
        req = make_request_envelope(
            identity=identity,
            message_id=f"msg-idx-{sid}",
            parent_message_id=None,
            from_agent=f"AgentWork:{cid}",
            to_agent="AgentMemory:global",
            msg_type="service.request",
            payload={
                "service": "memory.index_project",
                "request_id": f"req-idx-{sid}",
                "project_root": str(proj),
                "full": False,
                "db_path": str(tmp_path / "pag.sqlite3"),
            },
            now=RuntimeNow(),
        )
        client = BrokerJsonRpcClient(sock_path)
        out = client.call(req.to_dict(), timeout_s=120.0)
        assert out.get("ok") is True
        pl = out.get("payload")
        assert isinstance(pl, dict)
        ns = str(pl.get("namespace") or "").strip()
        assert ns
        db_file = Path(str(pl.get("db_path") or ""))
        assert db_file.is_file()
        store = SqlitePagStore(db_file)
        total = store.count_nodes(namespace=ns, level=None, include_stale=True)
        assert total >= 1
    finally:
        proc.terminate()
        proc.join(timeout=3.0)


def test_memory_index_unknown_service_still_rejected(tmp_path: Path) -> None:
    """Регрессия: неизвестный ``service`` по-прежнему ``unknown_service``."""
    runtime_dir = tmp_path / "rt2"
    paths = RuntimePaths(runtime_dir=runtime_dir)
    sock_path = paths.broker_socket(chat_id="chat-unk")
    trace_path = runtime_dir / "trace" / "trace-chat-unk.jsonl"
    cfg_dict = {
        "runtime_dir": str(runtime_dir),
        "socket_path": str(sock_path),
        "chat_id": "chat-unk",
        "namespace": "ns-u",
        "project_root": str(tmp_path),
        "trace_store_path": str(trace_path),
    }
    proc = multiprocessing.Process(target=_run_broker, args=(cfg_dict,))
    proc.daemon = True
    proc.start()
    try:
        deadline = time.time() + 8.0
        while time.time() < deadline and not sock_path.exists():
            time.sleep(0.05)
        assert sock_path.exists()
        cid = "chat-unk"
        identity = RuntimeIdentity(
            runtime_id="rt-unk",
            chat_id=cid,
            broker_id=f"broker-{cid}",
            trace_id="tr-unk",
            goal_id="x",
            namespace="ns-u",
        )
        req = make_request_envelope(
            identity=identity,
            message_id="m-unk-1",
            parent_message_id=None,
            from_agent=f"AgentWork:{cid}",
            to_agent="AgentMemory:global",
            msg_type="service.request",
            payload={
                "service": "memory.nonexistent_service",
                "request_id": "r-unk",
            },
            now=RuntimeNow(),
        )
        client = BrokerJsonRpcClient(sock_path)
        out = client.call(req.to_dict(), timeout_s=30.0)
        assert out.get("ok") is False
        err = out.get("error")
        assert isinstance(err, dict)
        assert err.get("code") == "unknown_service"
    finally:
        proc.terminate()
        proc.join(timeout=3.0)
