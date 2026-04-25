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
from typing import Any, Mapping

from agent_core.runtime.errors import RuntimeProtocolError
from agent_core.runtime.models import (
    CONTRACT_VERSION,
    RuntimeRequestEnvelope,
    RuntimeResponseEnvelope,
    make_response_envelope,
)
from agent_core.runtime.paths import RuntimePaths, default_runtime_dir
from agent_core.runtime.trace_store import JsonlTraceStore, TraceRow


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


@dataclass(frozen=True, slots=True)
class BrokerConfig:
    """Конфигурация broker процесса."""

    runtime_dir: Path
    socket_path: Path
    chat_id: str
    namespace: str
    project_root: str
    trace_store_path: Path


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

    def __init__(self, name: str, cmd: list[str]) -> None:
        self._name = name
        self._cmd = cmd
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


class AgentBroker:
    """Broker с routing и trace store."""

    def __init__(self, cfg: BrokerConfig) -> None:
        self._cfg = cfg
        self._trace = JsonlTraceStore(cfg.trace_store_path)
        self._subs = _LiveSubscribers()
        self._agents_lock = threading.Lock()
        self._agents: dict[str, _AgentProcess] = {}
        self._broker_id = f"broker-{cfg.chat_id}"

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
                "agent_core.runtime.subprocess_agents.work_agent",
                "--chat-id",
                self._cfg.chat_id,
                "--broker-id",
                self._broker_id,
                "--namespace",
                self._cfg.namespace,
            ]
            self._agents["AgentWork"] = _AgentProcess("AgentWork", cmd)

    def spawn_memory(self) -> None:
        """Поднять AgentMemory subprocess (MVP)."""
        with self._agents_lock:
            if "AgentMemory" in self._agents:
                return
            py = sys.executable
            cmd = [
                py,
                "-m",
                "agent_core.runtime.subprocess_agents.memory_agent",
                "--chat-id",
                self._cfg.chat_id,
                "--broker-id",
                self._broker_id,
                "--namespace",
                self._cfg.namespace,
            ]
            self._agents["AgentMemory"] = _AgentProcess("AgentMemory", cmd)

    def spawn_dummy(self) -> None:
        """Поднять internal AgentDummy (tests)."""
        with self._agents_lock:
            if "AgentDummy" in self._agents:
                return
            py = sys.executable
            cmd = [
                py,
                "-m",
                "agent_core.runtime.subprocess_agents.dummy_agent",
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

    def handle_request(
        self,
        req: RuntimeRequestEnvelope,
    ) -> RuntimeResponseEnvelope:
        """Обработать один runtime request envelope."""
        self.append_trace(req.to_dict())
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
        if req.type == "service.request":
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
            try:
                out = agent.request(req, timeout_s=1.0)
            except TimeoutError as e:
                return make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={"code": "runtime_timeout", "message": str(e)},
                )
            self.append_trace(out.to_dict())
            return out
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
                out = agent.request(req, timeout_s=2.0)
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
    cfg = BrokerConfig(
        runtime_dir=runtime_dir,
        socket_path=Path(args.socket_path).expanduser().resolve(),
        chat_id=str(args.chat_id),
        namespace=str(args.namespace),
        project_root=str(args.project_root),
        trace_store_path=_trace_store_path(paths, chat_id=str(args.chat_id)),
    )
    if not cfg.chat_id.strip() or not cfg.namespace.strip():
        raise RuntimeProtocolError(
            code="invalid_args",
            message="chat_id/namespace",
        )
    if CONTRACT_VERSION != "ailit_agent_runtime_v1":
        raise RuntimeProtocolError(code="contract", message="version mismatch")
    run_broker_server(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
