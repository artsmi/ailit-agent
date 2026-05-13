"""AilitRuntimeSupervisor.

Registry broker-ов и локальный Unix-socket API (G8.2).
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ailit_runtime.broker_workspace_config import (
    BrokerWorkspaceEntry,
    BrokerWorkspaceFile,
    parse_workspace_extras_from_request,
    write_broker_workspace_file,
)
from ailit_runtime.errors import RuntimeProtocolError
from ailit_runtime.paths import RuntimePaths, default_runtime_dir


@dataclass(frozen=True, slots=True)
class BrokerRecord:
    """Состояние broker-а, управляемого supervisor-ом."""

    chat_id: str
    primary_namespace: str
    primary_project_root: str
    workspace: tuple[BrokerWorkspaceEntry, ...]
    endpoint: str
    pid: int | None
    state: str
    created_at: float
    last_seen: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "namespace": self.primary_namespace,
            "project_root": self.primary_project_root,
            "primary_namespace": self.primary_namespace,
            "primary_project_root": self.primary_project_root,
            "workspace": [
                {"namespace": e.namespace, "project_root": str(e.project_root)}
                for e in self.workspace
            ],
            "endpoint": self.endpoint,
            "pid": self.pid,
            "state": self.state,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
        }


@dataclass(slots=True)
class SupervisorConfig:
    """Конфиг supervisor."""

    runtime_dir: Path
    broker_cmd: tuple[str, ...] = field(default_factory=tuple)
    healthcheck_timeout_s: float = 0.2


class BrokerProcessManager:
    """Запуск и остановка placeholder broker subprocess."""

    def __init__(self, paths: RuntimePaths, cmd: tuple[str, ...]) -> None:
        self._paths = paths
        self._cmd = cmd

    def spawn(
        self,
        *,
        chat_id: str,
        workspace_spec: BrokerWorkspaceFile,
    ) -> tuple[int, str]:
        """Запустить broker и вернуть (pid, endpoint)."""
        sock = self._paths.broker_socket(chat_id=chat_id)
        endpoint = f"unix://{sock}"
        safe = "".join(c for c in chat_id if c.isalnum() or c in ("-", "_"))
        ws_dir = self._paths.runtime_dir / "broker_workspace"
        ws_path = ws_dir / f"{safe}.json"
        write_broker_workspace_file(ws_path, workspace_spec)
        py = sys.executable
        if self._cmd:
            cmd = [*self._cmd, str(sock)]
        else:
            cmd = [
                py,
                "-m",
                "ailit_runtime.broker",
                "--runtime-dir",
                str(self._paths.runtime_dir),
                "--socket-path",
                str(sock),
                "--chat-id",
                str(chat_id),
                "--namespace",
                str(workspace_spec.primary_namespace),
                "--project-root",
                str(workspace_spec.primary_project_root),
                "--workspace-config",
                str(ws_path),
            ]
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        return int(p.pid), endpoint

    def stop(self, *, pid: int) -> None:
        """Остановить процесс broker."""
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            return

    def is_alive(self, *, pid: int) -> bool:
        """True, если процесс жив."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


class AilitRuntimeSupervisor:
    """Supervisor: принимает API запросы и управляет broker registry."""

    def __init__(self, cfg: SupervisorConfig) -> None:
        self._paths = RuntimePaths(runtime_dir=cfg.runtime_dir)
        self._cfg = cfg
        self._mgr = BrokerProcessManager(self._paths, cfg.broker_cmd)
        self._lock = threading.Lock()
        self._brokers: dict[str, BrokerRecord] = {}
        self._created_at = time.time()

    @property
    def paths(self) -> RuntimePaths:
        """Пути runtime."""
        return self._paths

    def status(self) -> Mapping[str, Any]:
        """Сводка supervisor."""
        with self._lock:
            brokers = list(self._brokers.values())
        return {
            "runtime_dir": str(self._paths.runtime_dir),
            "uptime_s": max(0.0, time.time() - self._created_at),
            "broker_count": len(brokers),
            "brokers_failed": sum(1 for b in brokers if b.state == "failed"),
        }

    def list_brokers(self) -> tuple[BrokerRecord, ...]:
        """Список broker-ов (с обновлением состояния)."""
        with self._lock:
            for chat_id, rec in list(self._brokers.items()):
                self._brokers[chat_id] = self._refresh(rec)
            return tuple(self._brokers.values())

    def create_or_get_broker(
        self,
        *,
        chat_id: str,
        primary_namespace: str,
        primary_project_root: str,
        workspace: tuple[BrokerWorkspaceEntry, ...],
    ) -> BrokerRecord:
        """Создать broker для chat_id или вернуть существующий."""
        if not chat_id.strip():
            raise RuntimeProtocolError(
                code="invalid_args",
                message="chat_id required",
            )
        pn = str(primary_namespace or "").strip()
        pp = str(primary_project_root or "").strip()
        if not pn or not pp:
            raise RuntimeProtocolError(
                code="invalid_args",
                message="primary_namespace and primary_project_root required",
            )
        spec = BrokerWorkspaceFile(
            primary_namespace=pn,
            primary_project_root=Path(pp).expanduser().resolve(),
            extra=workspace,
        )
        with self._lock:
            existing = self._brokers.get(chat_id)
            if existing is not None:
                refreshed = self._refresh(existing)
                if refreshed.state == "running":
                    self._brokers[chat_id] = refreshed
                    return refreshed
            pid, endpoint = self._mgr.spawn(
                chat_id=chat_id,
                workspace_spec=spec,
            )
            now = time.time()
            rec = BrokerRecord(
                chat_id=chat_id,
                primary_namespace=spec.primary_namespace,
                primary_project_root=str(spec.primary_project_root),
                workspace=workspace,
                endpoint=endpoint,
                pid=pid,
                state="running",
                created_at=now,
                last_seen=now,
            )
            self._brokers[chat_id] = rec
            return rec

    def stop_broker(self, *, chat_id: str) -> BrokerRecord | None:
        """Остановить broker и пометить failed."""
        with self._lock:
            rec = self._brokers.get(chat_id)
            if rec is None:
                return None
            if rec.pid is not None:
                self._mgr.stop(pid=rec.pid)
            now = time.time()
            updated = BrokerRecord(
                chat_id=rec.chat_id,
                primary_namespace=rec.primary_namespace,
                primary_project_root=rec.primary_project_root,
                workspace=rec.workspace,
                endpoint=rec.endpoint,
                pid=rec.pid,
                state="failed",
                created_at=rec.created_at,
                last_seen=now,
            )
            self._brokers[chat_id] = updated
            return updated

    def _refresh(self, rec: BrokerRecord) -> BrokerRecord:
        if rec.pid is None:
            return rec
        if not self._mgr.is_alive(pid=rec.pid):
            return BrokerRecord(
                chat_id=rec.chat_id,
                primary_namespace=rec.primary_namespace,
                primary_project_root=rec.primary_project_root,
                workspace=rec.workspace,
                endpoint=rec.endpoint,
                pid=rec.pid,
                state="failed",
                created_at=rec.created_at,
                last_seen=rec.last_seen,
            )
        return rec


class _SupervisorHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        sup: AilitRuntimeSupervisor = self.server.supervisor  # type: ignore[attr-defined]  # noqa: E501
        line = (
            self.rfile.readline(1_000_000)
            .decode("utf-8", errors="replace")
            .strip()
        )
        if not line:
            self.wfile.write(b"{\"ok\":false,\"error\":\"empty\"}\n")
            return
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            self.wfile.write(
                json.dumps(
                    {"ok": False, "error": f"json_decode_error: {e}"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            return
        if not isinstance(req, dict):
            self.wfile.write(b"{\"ok\":false,\"error\":\"invalid_shape\"}\n")
            return
        cmd = str(req.get("cmd", "") or "")
        try:
            resp = _dispatch_cmd(sup, cmd, req)
        except RuntimeProtocolError as e:
            resp = {
                "ok": False,
                "error": {"code": e.code, "message": e.message},
            }
        except Exception as e:  # noqa: BLE001
            resp = {
                "ok": False,
                "error": {"code": "internal_error", "message": str(e)},
            }
        self.wfile.write(
            json.dumps(
                resp,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )


class _UnixSupervisorServer(socketserver.UnixStreamServer):
    supervisor: AilitRuntimeSupervisor

    def server_close(self) -> None:
        try:
            Path(self.server_address).unlink(  # type: ignore[arg-type]
                missing_ok=True,
            )
        except Exception:
            pass
        super().server_close()


def _dispatch_cmd(
    sup: AilitRuntimeSupervisor,
    cmd: str,
    req: Mapping[str, Any],
) -> Mapping[str, Any]:
    if cmd == "status":
        return {"ok": True, "result": dict(sup.status())}
    if cmd == "brokers":
        rows = [b.to_dict() for b in sup.list_brokers()]
        return {"ok": True, "result": {"brokers": rows}}
    if cmd == "create_or_get_broker":
        chat_id = str(req.get("chat_id", "") or "")
        primary_namespace = str(
            req.get("primary_namespace", "") or "",
        ).strip()
        primary_project_root = str(
            req.get("primary_project_root", "") or "",
        ).strip()
        if not primary_namespace:
            primary_namespace = str(req.get("namespace", "") or "").strip()
        if not primary_project_root:
            primary_project_root = str(
                req.get("project_root", "") or "",
            ).strip()
        raw_workspace = req.get("workspace")
        if raw_workspace is None:
            workspace_extras = ()
        else:
            workspace_extras = parse_workspace_extras_from_request(
                raw_workspace,
            )
        rec = sup.create_or_get_broker(
            chat_id=chat_id,
            primary_namespace=primary_namespace,
            primary_project_root=primary_project_root,
            workspace=workspace_extras,
        )
        return {"ok": True, "result": rec.to_dict()}
    if cmd == "stop_broker":
        chat_id = str(req.get("chat_id", "") or "")
        rec = sup.stop_broker(chat_id=chat_id)
        return {
            "ok": True,
            "result": rec.to_dict() if rec is not None else None,
        }
    raise RuntimeProtocolError(
        code="unknown_cmd",
        message=f"unknown cmd: {cmd!r}",
    )


def run_supervisor_server(
    *,
    runtime_dir: Path | None = None,
    broker_cmd: tuple[str, ...] = (),
) -> None:
    """Запустить supervisor server (blocking)."""
    rd = (
        Path(runtime_dir)
        if runtime_dir is not None
        else default_runtime_dir()
    )
    cfg = SupervisorConfig(runtime_dir=rd, broker_cmd=broker_cmd)
    sup = AilitRuntimeSupervisor(cfg)
    paths = sup.paths
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    sock = paths.supervisor_socket
    try:
        sock.unlink()
    except FileNotFoundError:
        pass
    with _UnixSupervisorServer(str(sock), _SupervisorHandler) as srv:
        srv.supervisor = sup  # type: ignore[attr-defined]
        srv.serve_forever(poll_interval=0.2)


def supervisor_request(
    *,
    socket_path: Path,
    request: Mapping[str, Any],
    timeout_s: float = 1.0,
) -> Mapping[str, Any]:
    """Синхронный клиент для supervisor."""
    payload = json.dumps(
        dict(request),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if "\n" in payload:
        raise RuntimeProtocolError(
            code="invalid_request",
            message="request must be single-line json",
        )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout_s)
        s.connect(str(socket_path))
        s.sendall(payload.encode("utf-8") + b"\n")
        data = (
            s.recv(1_000_000)
            .decode("utf-8", errors="replace")
            .strip()
        )
    try:
        resp = json.loads(data) if data else {}
    except json.JSONDecodeError as e:
        raise RuntimeProtocolError(
            code="invalid_response",
            message=str(e),
        ) from e
    if not isinstance(resp, dict):
        raise RuntimeProtocolError(
            code="invalid_response",
            message="response must be dict",
        )
    return resp
