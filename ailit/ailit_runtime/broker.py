"""AgentBroker process: ROS-like routing for topic/service/action (G8.3).

MVP transport:
- Unix domain socket server (stream).
- Requests and events are JSON-lines with RuntimeRequestEnvelope /
  RuntimeResponseEnvelope compatible shape.

Broker responsibilities:
- Spawn per-chat subprocess agents (G8.4) and route messages.
- Append durable trace rows and provide live trace subscription.
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from agent_memory.config.agent_memory_ailit_config import (
    agent_memory_rpc_timeout_s,
    load_merged_ailit_config_for_memory,
)
from ailit_runtime.errors import RuntimeProtocolError
from ailit_runtime.models import (
    CONTRACT_VERSION,
    RuntimeIdentity,
    RuntimeRequestEnvelope,
    RuntimeResponseEnvelope,
    make_request_envelope,
    make_response_envelope,
)
from ailit_runtime.broker_workspace_config import (
    BrokerWorkspaceEntry,
    read_broker_workspace_file,
)
from ailit_runtime.paths import RuntimePaths, default_runtime_dir
from ailit_runtime.trace_store import JsonlTraceStore, TraceRow


def _json_dumps(obj: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(obj),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _safe_uuid() -> str:
    return str(uuid.uuid4())


RUNTIME_CANCEL_ACTIVE_TURN: str = "runtime.cancel_active_turn"
MEMORY_CANCEL_QUERY_SERVICE: str = "memory.cancel_query_context"


@dataclass(frozen=True, slots=True)
class BrokerConfig:
    """Конфигурация broker процесса."""

    runtime_dir: Path
    socket_path: Path
    chat_id: str
    namespace: str
    project_root: str
    trace_store_path: Path
    workspace_config_path: Path | None
    workspace_entries: tuple[BrokerWorkspaceEntry, ...]


class _LiveSubscribers:
    """Thread-safe список подписчиков на trace."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[socket.socket] = []

    def add(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(0.2)
        except OSError:
            pass
        with self._lock:
            self._subs.append(conn)

    def remove(self, conn: socket.socket) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s is not conn]

    def broadcast(self, line: bytes) -> None:
        with self._lock:
            subs = list(self._subs)
        for s in subs:
            try:
                import select

                _, writable, _ = select.select([], [s], [], 0.0)
                if not writable:
                    continue
                s.sendall(line)
            except OSError:
                self.remove(s)


class _AgentProcess:
    """Subprocess агент с JSON-lines протоколом stdin/stdout."""

    def __init__(
        self,
        name: str,
        cmd: list[str],
        *,
        on_outbound_event: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self._name = name
        self._cmd = cmd
        self._on_outbound_event = on_outbound_event
        self._proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            close_fds=True,
            start_new_session=True,
        )
        if self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("failed to open agent pipes")
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout
        self._stdin_lock = threading.Lock()
        self._pending: dict[str, "queue.Queue[RuntimeResponseEnvelope]"] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(
            target=self._read_loop, name=f"{name}-stdout", daemon=True
        )
        self._reader.start()

    @property
    def pid(self) -> int:
        return int(self._proc.pid or 0)

    def stop(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def request(
        self, env: RuntimeRequestEnvelope, *, timeout_s: float
    ) -> RuntimeResponseEnvelope:
        q: "queue.Queue[RuntimeResponseEnvelope]" = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[env.message_id] = q
        with self._stdin_lock:
            self._stdin.write(env.to_json_line() + "\n")
            self._stdin.flush()
        try:
            return q.get(timeout=timeout_s)
        except queue.Empty as e:
            raise TimeoutError(f"agent timeout: {self._name}") from e
        finally:
            with self._lock:
                self._pending.pop(env.message_id, None)

    def send_oneway(self, env: RuntimeRequestEnvelope) -> None:
        """Отправить сообщение агенту без ожидания ответа."""
        with self._stdin_lock:
            self._stdin.write(env.to_json_line() + "\n")
            self._stdin.flush()

    def _read_loop(self) -> None:
        while True:
            line = self._stdout.readline()
            if not line:
                return
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if "ok" not in obj:
                # Агент может эмитить runtime события: topic.publish/action.*.
                # Broker добавляет их в trace и рассылает подписчикам.
                try:
                    env_req = RuntimeRequestEnvelope.from_dict(obj)
                except Exception:
                    continue
                if self._on_outbound_event is not None:
                    try:
                        self._on_outbound_event(env_req.to_dict())
                    except Exception:
                        pass
                continue
            try:
                env = RuntimeResponseEnvelope(
                    contract_version=str(obj.get("contract_version", "")),
                    runtime_id=str(obj.get("runtime_id", "")),
                    chat_id=str(obj.get("chat_id", "")),
                    broker_id=str(obj.get("broker_id", "")),
                    trace_id=str(obj.get("trace_id", "")),
                    message_id=str(obj.get("message_id", "")),
                    parent_message_id=obj.get("parent_message_id"),
                    goal_id=str(obj.get("goal_id", "")),
                    namespace=str(obj.get("namespace", "")),
                    from_agent=str(obj.get("from_agent", "")),
                    to_agent=str(obj.get("to_agent", "")),
                    created_at=str(obj.get("created_at", "")),
                    type=str(obj.get("type", "")),
                    ok=bool(obj.get("ok", False)),
                    payload=obj.get("payload") if isinstance(obj.get("payload"), dict) else {},  # noqa: E501
                    error=obj.get("error") if isinstance(obj.get("error"), dict) else None,  # noqa: E501
                )
                env.validate()
            except Exception:
                continue
            with self._lock:
                q = self._pending.get(env.message_id)
            if q is not None:
                try:
                    q.put_nowait(env)
                except queue.Full:
                    pass

    def inject_synthetic_response(
        self,
        message_id: str,
        env: RuntimeResponseEnvelope,
    ) -> bool:
        """Поместить ответ в очередь ожидающего RPC (cooperative cancel)."""
        with self._lock:
            q = self._pending.get(message_id)
        if q is None:
            return False
        try:
            q.put_nowait(env)
            return True
        except queue.Full:
            return True


class AgentBroker:
    """Broker с routing и trace store."""

    def __init__(self, cfg: BrokerConfig) -> None:
        self._cfg = cfg
        self._trace = JsonlTraceStore(cfg.trace_store_path)
        self._subs = _LiveSubscribers()
        self._agents_lock = threading.Lock()
        self._agents: dict[str, _AgentProcess] = {}
        self._broker_id = f"broker-{cfg.chat_id}"
        self._mem_rpc_lock = threading.Lock()
        self._mem_rpc_active: dict[
            tuple[str, str],
            RuntimeRequestEnvelope,
        ] = {}

    @property
    def broker_id(self) -> str:
        return self._broker_id

    def spawn_work(self) -> None:
        """Поднять AgentWork subprocess (MVP)."""
        with self._agents_lock:
            if "AgentWork" in self._agents:
                return
            py = sys.executable
            cmd = [
                py,
                "-m",
                "ailit_runtime.subprocess_agents.work_agent",
                "--chat-id",
                self._cfg.chat_id,
                "--broker-id",
                self._broker_id,
                "--broker-socket-path",
                str(self._cfg.socket_path),
                "--namespace",
                self._cfg.namespace,
            ]
            if self._cfg.workspace_config_path is not None:
                cmd.extend(
                    [
                        "--workspace-config",
                        str(self._cfg.workspace_config_path),
                    ],
                )
            self._agents["AgentWork"] = _AgentProcess(
                "AgentWork",
                cmd,
                on_outbound_event=self.append_trace,
            )

    def spawn_memory(self) -> None:
        """Поднять AgentMemory subprocess (MVP)."""
        with self._agents_lock:
            if "AgentMemory" in self._agents:
                return
            py = sys.executable
            cmd = [
                py,
                "-m",
                "ailit_runtime.subprocess_agents.memory_agent",
                "--chat-id",
                "global",
                "--broker-id",
                self._broker_id,
                "--namespace",
                self._cfg.namespace,
            ]
            if self._cfg.workspace_config_path is not None:
                cmd.extend(
                    [
                        "--workspace-config",
                        str(self._cfg.workspace_config_path),
                    ],
                )
            self._agents["AgentMemory"] = _AgentProcess(
                "AgentMemory",
                cmd,
                on_outbound_event=self.append_trace,
            )

    def spawn_dummy(self) -> None:
        """Поднять internal AgentDummy (tests)."""
        with self._agents_lock:
            if "AgentDummy" in self._agents:
                return
            py = sys.executable
            cmd = [
                py,
                "-m",
                "ailit_runtime.subprocess_agents.dummy_agent",
                "--chat-id",
                self._cfg.chat_id,
                "--broker-id",
                self._broker_id,
                "--namespace",
                self._cfg.namespace,
            ]
            self._agents["AgentDummy"] = _AgentProcess("AgentDummy", cmd)

    def _ensure_agent(self, agent_type: str) -> _AgentProcess | None:
        agent_type = str(agent_type).strip()
        if agent_type == "AgentDummy":
            self.spawn_dummy()
        elif agent_type == "AgentWork":
            self.spawn_work()
        elif agent_type == "AgentMemory":
            self.spawn_memory()
        with self._agents_lock:
            return self._agents.get(agent_type)

    @staticmethod
    def _agent_type_from_to_agent(to_agent: str) -> str:
        ta = str(to_agent or "").strip()
        if "AgentDummy" in ta:
            return "AgentDummy"
        if "AgentMemory" in ta:
            return "AgentMemory"
        if "AgentWork" in ta:
            return "AgentWork"
        return ""

    def append_trace(self, env: Mapping[str, Any]) -> None:
        row = TraceRow(data=dict(env))
        self._trace.append(row)
        self._subs.broadcast(_json_dumps(env))

    def _handle_runtime_cancel_active_turn(
        self,
        req: RuntimeRequestEnvelope,
    ) -> RuntimeResponseEnvelope:
        """Идемпотентный cooperative cancel (plan §Замороженный контракт)."""
        cid = str(req.chat_id or "").strip()
        pl = req.payload if isinstance(req.payload, dict) else {}
        utid = str(pl.get("user_turn_id") or "").strip()
        if not utid:
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "missing_user_turn_id",
                    "message": "user_turn_id required",
                },
            )
        if cid != str(self._cfg.chat_id or "").strip():
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "chat_mismatch",
                    "message": f"expected {self._cfg.chat_id!r}",
                },
            )
        self.spawn_work()
        self.spawn_memory()
        key = (cid, utid)
        with self._mem_rpc_lock:
            mem_req = self._mem_rpc_active.get(key)
        qid = ""
        if mem_req is not None:
            mpl = (
                mem_req.payload if isinstance(mem_req.payload, dict) else {}
            )
            qid = str(mpl.get("query_id") or "").strip()
        identity = RuntimeIdentity(
            runtime_id=req.runtime_id,
            chat_id=cid,
            broker_id=req.broker_id,
            trace_id=req.trace_id,
            goal_id=req.goal_id,
            namespace=req.namespace,
        )
        work = self._ensure_agent("AgentWork")
        mem = self._ensure_agent("AgentMemory")
        if work is not None and work.is_alive():
            wreq = make_request_envelope(
                identity=identity,
                message_id=_safe_uuid(),
                parent_message_id=req.message_id,
                from_agent=str(req.from_agent or "client:cancel"),
                to_agent=f"AgentWork:{cid}",
                msg_type="service.request",
                payload={
                    "action": RUNTIME_CANCEL_ACTIVE_TURN,
                    "user_turn_id": utid,
                    "chat_id": cid,
                },
            )
            try:
                work.send_oneway(wreq)
            except Exception:
                pass
        if mem is not None and mem.is_alive() and qid:
            mreq = make_request_envelope(
                identity=identity,
                message_id=_safe_uuid(),
                parent_message_id=req.message_id,
                from_agent=str(req.from_agent or "client:cancel"),
                to_agent="AgentMemory:global",
                msg_type="service.request",
                payload={
                    "service": MEMORY_CANCEL_QUERY_SERVICE,
                    "query_id": qid,
                    "user_turn_id": utid,
                    "chat_id": cid,
                },
            )
            try:
                mem.send_oneway(mreq)
            except Exception:
                pass
        if mem is not None and mem.is_alive() and mem_req is not None:
            syn = make_response_envelope(
                request=mem_req,
                ok=False,
                payload={},
                error={
                    "code": "memory_query_cancelled",
                    "message": "cooperative cancel",
                },
            )
            mem.inject_synthetic_response(mem_req.message_id, syn)
        return make_response_envelope(
            request=req,
            ok=True,
            payload={
                "cancelled": True,
                "user_turn_id": utid,
                "query_id": qid or "",
            },
            error=None,
        )

    def handle_request(
        self,
        req: RuntimeRequestEnvelope,
    ) -> RuntimeResponseEnvelope:
        """Обработать один runtime request envelope."""
        self.append_trace(req.to_dict())
        if req.type == "service.request":
            pl0 = req.payload if isinstance(req.payload, dict) else {}
            svc0 = str(pl0.get("service", "") or "").strip()
            act0 = str(pl0.get("action", "") or "").strip()
            cancel_hit = (
                act0 == RUNTIME_CANCEL_ACTIVE_TURN
                or svc0 == RUNTIME_CANCEL_ACTIVE_TURN
            )
            if cancel_hit:
                out = self._handle_runtime_cancel_active_turn(req)
                self.append_trace(out.to_dict())
                return out

            to_agent = req.to_agent or ""
            agent_type = self._agent_type_from_to_agent(to_agent)
            agent = self._ensure_agent(agent_type) if agent_type else None
            if agent is None or not agent.is_alive():
                return make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={
                        "code": "agent_unavailable",
                        "message": agent_type or str(to_agent),
                    },
                )
            inflight_key: tuple[str, str] | None = None
            try:
                if agent_type == "AgentMemory":
                    try:
                        _merged_am = load_merged_ailit_config_for_memory()
                    except Exception:
                        _merged_am = {}
                    svc_timeout = float(
                        agent_memory_rpc_timeout_s(_merged_am),
                    )
                else:
                    svc_timeout = 15.0
                plm = req.payload if isinstance(req.payload, dict) else {}
                svc_n = str(plm.get("service", "") or "")
                mem_q = svc_n == "memory.query_context"
                if agent_type == "AgentMemory" and mem_q:
                    uid = str(plm.get("user_turn_id") or "").strip()
                    qid = str(plm.get("query_id") or "").strip()
                    if uid and qid:
                        inflight_key = (
                            str(req.chat_id or "").strip(),
                            uid,
                        )
                        with self._mem_rpc_lock:
                            self._mem_rpc_active[inflight_key] = req
                out = agent.request(
                    req,
                    timeout_s=svc_timeout,
                )
            except TimeoutError as e:
                return make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={"code": "runtime_timeout", "message": str(e)},
                )
            finally:
                if inflight_key is not None:
                    with self._mem_rpc_lock:
                        cur = self._mem_rpc_active.get(inflight_key)
                        same = (
                            cur is not None
                            and cur.message_id == req.message_id
                        )
                        if same:
                            self._mem_rpc_active.pop(inflight_key, None)
            self.append_trace(out.to_dict())
            return out
        if req.type == "topic.publish":
            # Best-effort fan-out to all spawned agents (MVP).
            self.spawn_dummy()
            self.spawn_work()
            self.spawn_memory()
            with self._agents_lock:
                agents = list(self._agents.values())
            for a in agents:
                if a.is_alive():
                    try:
                        a.send_oneway(req)
                    except Exception:
                        continue
            resp = make_response_envelope(
                request=req,
                ok=True,
                payload={"delivered": True},
                error=None,
            )
            self.append_trace(resp.to_dict())
            return resp
        if req.type == "action.start":
            to_agent = req.to_agent or ""
            agent_type = self._agent_type_from_to_agent(to_agent)
            if not agent_type:
                # UX default: work action without explicit to_agent.
                action = str(req.payload.get("action", "") or "")
                if action == "work.handle_user_prompt":
                    agent_type = "AgentWork"
            agent = self._ensure_agent(agent_type) if agent_type else None
            if agent is None or not agent.is_alive():
                return make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={
                        "code": "agent_unavailable",
                        "message": agent_type or str(to_agent),
                    },
                )
            try:
                out = agent.request(req, timeout_s=30.0)
            except TimeoutError as e:
                return make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={"code": "runtime_timeout", "message": str(e)},
                )
            self.append_trace(out.to_dict())
            return out
        return make_response_envelope(
            request=req,
            ok=False,
            payload={},
            error={"code": "unknown_type", "message": str(req.type)},
        )


class _BrokerHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        broker: AgentBroker = self.server.broker  # type: ignore[attr-defined]
        raw = (
            self.rfile.readline(1_000_000)
            .decode("utf-8", errors="replace")
            .strip()
        )
        if not raw:
            self.wfile.write(b"{\"ok\":false,\"error\":\"empty\"}\n")
            return
        if raw == "ping":
            self.wfile.write(b"pong\n")
            return
        if raw == "{\"cmd\":\"subscribe_trace\"}":
            # Keep connection open for live trace JSON-lines.
            broker._subs.add(self.connection)  # noqa: SLF001
            try:
                while True:
                    time.sleep(3600)
            finally:
                broker._subs.remove(self.connection)  # noqa: SLF001
            return
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            self.wfile.write(
                _json_dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "json_decode_error",
                            "message": str(e),
                        },
                    }
                )
            )
            return
        if not isinstance(obj, dict):
            self.wfile.write(
                _json_dumps(
                    {
                        "ok": False,
                        "error": {"code": "invalid_shape", "message": "dict"},
                    }
                )
            )
            return
        try:
            req = RuntimeRequestEnvelope.from_dict(obj)
        except Exception as e:  # noqa: BLE001
            self.wfile.write(
                _json_dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "invalid_envelope",
                            "message": str(e),
                        },
                    }
                )
            )
            return
        resp = broker.handle_request(req)
        self.wfile.write(resp.to_json_line().encode("utf-8") + b"\n")


class _UnixBrokerServer(
    socketserver.ThreadingMixIn,
    socketserver.UnixStreamServer,
):
    broker: AgentBroker
    daemon_threads = True

    def server_close(self) -> None:
        try:
            Path(self.server_address).unlink(  # type: ignore[arg-type]
                missing_ok=True,
            )
        except Exception:
            pass
        super().server_close()


def _trace_store_path(paths: RuntimePaths, *, chat_id: str) -> Path:
    safe = "".join(c for c in chat_id if c.isalnum() or c in ("-", "_"))
    return paths.runtime_dir / "trace" / f"trace-{safe}.jsonl"


def run_broker_server(cfg: BrokerConfig) -> None:
    """Запустить broker server (blocking)."""
    cfg.socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cfg.socket_path.unlink()
    except FileNotFoundError:
        pass
    broker = AgentBroker(cfg)
    with _UnixBrokerServer(str(cfg.socket_path), _BrokerHandler) as srv:
        srv.broker = broker  # type: ignore[attr-defined]
        srv.serve_forever(poll_interval=0.2)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ailit-runtime-broker")
    p.add_argument("--runtime-dir", type=str, default="")
    p.add_argument("--socket-path", type=str, required=True)
    p.add_argument("--chat-id", type=str, required=True)
    p.add_argument("--namespace", type=str, required=True)
    p.add_argument("--project-root", type=str, required=True)
    p.add_argument(
        "--workspace-config",
        type=str,
        default="",
        help="JSON: primary_namespace, primary_project_root, workspace[]",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint (internal)."""
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    runtime_dir = (
        Path(args.runtime_dir).expanduser().resolve()
        if str(args.runtime_dir).strip()
        else default_runtime_dir()
    )
    paths = RuntimePaths(runtime_dir=runtime_dir)
    ws_arg = str(getattr(args, "workspace_config", "") or "").strip()
    ws_path = Path(ws_arg).expanduser().resolve() if ws_arg else None
    if ws_path is not None:
        ws_file = read_broker_workspace_file(ws_path)
        ws_entries = ws_file.all_entries
        primary_ns = ws_file.primary_namespace
        primary_root = str(ws_file.primary_project_root)
    else:
        ws_entries = (
            BrokerWorkspaceEntry(
                namespace=str(args.namespace),
                project_root=Path(args.project_root).expanduser().resolve(),
            ),
        )
        primary_ns = str(args.namespace)
        primary_root = str(Path(args.project_root).expanduser().resolve())
    cfg = BrokerConfig(
        runtime_dir=runtime_dir,
        socket_path=Path(args.socket_path).expanduser().resolve(),
        chat_id=str(args.chat_id),
        namespace=primary_ns,
        project_root=primary_root,
        trace_store_path=_trace_store_path(paths, chat_id=str(args.chat_id)),
        workspace_config_path=ws_path,
        workspace_entries=ws_entries,
    )
    if not cfg.chat_id.strip() or not cfg.namespace.strip():
        raise RuntimeProtocolError(
            code="invalid_args",
            message="chat_id/namespace",
        )
    if not str(cfg.project_root or "").strip():
        raise RuntimeProtocolError(
            code="invalid_args",
            message="project_root",
        )
    if CONTRACT_VERSION != "ailit_agent_runtime_v1":
        raise RuntimeProtocolError(code="contract", message="version mismatch")
    run_broker_server(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
