"""G20.6: локальный HTTP + trace ``subscribe_trace`` для ``ailit memory``."""

from __future__ import annotations

import json
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final, Mapping
from urllib.parse import parse_qs, urlparse

from ailit_runtime.broker_json_client import (
    BrokerTraceBackgroundCapture,
    BrokerTransportError,
)

_STATIC_DIR: Final[Path] = (
    Path(__file__).resolve().parent / "static" / "memory_viz"
)
_MAX_TRACE_SERVE: Final[int] = 500
_MAX_RAW_SCAN: Final[int] = 4000


class _ReuseThreadingHTTPServer(ThreadingHTTPServer):
    """Порт 0: переиспользование сокета после быстрых рестартов dev."""

    allow_reuse_address = True


def memory_viz_disabled(args: object) -> bool:
    """D6: opt-out только флагом CLI (без env)."""
    return bool(getattr(args, "no_memory_viz", False))


def memory_viz_trace_row_visible(row: Mapping[str, Any]) -> bool:
    """
    G20.6 whitelist: релевантные envelope для memory / service RPC.

    Проверка: ``tests/runtime/test_broker_routing.py`` + trace broadcast
    в ``ailit_runtime.broker.AgentBroker.append_trace``.
    """
    t = str(row.get("type") or row.get("msg_type") or "").strip()
    if t in {"service.request", "service.response"}:
        return True
    fa = str(row.get("from_agent") or "")
    ta = str(row.get("to_agent") or "")
    if "AgentMemory" in fa or "AgentMemory" in ta:
        return True
    pl = row.get("payload")
    if isinstance(pl, dict):
        svc = str(pl.get("service") or "")
        if svc.startswith("memory."):
            return True
    return False


def _filtered_trace_rows(
    rows: list[dict[str, Any]],
    *,
    max_out: int,
) -> list[dict[str, Any]]:
    tail = rows[-_MAX_RAW_SCAN:]
    out: list[dict[str, Any]] = []
    for r in tail:
        if memory_viz_trace_row_visible(r):
            out.append(r)
    return out[-max_out:]


@dataclass
class MemoryVizRuntime:
    """HTTP-сервер + фоновый ``BrokerTraceBackgroundCapture``."""

    socket_path: Path
    pag_namespace: str
    db_path: Path | None = None
    _capture: BrokerTraceBackgroundCapture | None = field(
        default=None,
        repr=False,
    )
    _server: ThreadingHTTPServer | None = field(default=None, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _port: int = 0

    def start(self) -> bool:
        """Поднять capture и HTTP; при ошибке вернуть ``False``."""
        try:
            cap = BrokerTraceBackgroundCapture(self.socket_path)
            cap.start(connect_timeout_s=5.0)
            time.sleep(0.08)
        except (OSError, BrokerTransportError, RuntimeError) as exc:
            sys.stderr.write(f"memory viz: trace subscribe failed: {exc}\n")
            return False

        handler = _make_handler(
            capture=cap,
            namespace=self.pag_namespace,
            db_path=self.db_path,
        )
        try:
            httpd = _ReuseThreadingHTTPServer(("127.0.0.1", 0), handler)
        except OSError as exc:
            sys.stderr.write(f"memory viz: http listen failed: {exc}\n")
            cap.stop()
            return False

        self._capture = cap
        self._server = httpd
        self._port = int(httpd.server_address[1])
        th = threading.Thread(
            target=httpd.serve_forever,
            name="memory-viz-http",
            daemon=True,
        )
        th.start()
        self._thread = th
        return True

    def open_browser(self) -> None:
        """Открыть вкладку (D5); не критично при сбое."""
        if self._port <= 0:
            return
        ns_q = self.pag_namespace.strip()
        q = f"http://127.0.0.1:{self._port}/"
        if ns_q:
            from urllib.parse import quote

            q = f"{q}?namespace={quote(ns_q)}"
        try:
            webbrowser.open(q)
        except Exception as exc:
            sys.stderr.write(f"memory viz: browser open failed: {exc}\n")
        sys.stderr.write(f"memory viz: {q}\n")

    def stop(self) -> None:
        """Остановить HTTP и trace."""
        srv = self._server
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=4.0)
            self._thread = None
        if self._capture is not None:
            self._capture.stop()
            self._capture = None


def maybe_start_memory_viz(
    args: object,
    *,
    socket_path: Path,
    pag_namespace: str,
    db_path: Path | None = None,
) -> MemoryVizRuntime | None:
    """Старт viz или ``None`` (D6 / ошибка старта)."""
    if memory_viz_disabled(args):
        return None
    rt = MemoryVizRuntime(
        socket_path,
        pag_namespace=str(pag_namespace or "").strip(),
        db_path=db_path,
    )
    if not rt.start():
        return None
    rt.open_browser()
    return rt


def _send_json(
    handler: BaseHTTPRequestHandler,
    payload: Mapping[str, Any],
    *,
    status: int = 200,
) -> None:
    body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
    ct = "application/json; charset=utf-8"
    handler.send_response(status)
    handler.send_header("Content-Type", ct)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _make_handler(
    *,
    capture: BrokerTraceBackgroundCapture,
    namespace: str,
    db_path: Path | None,
) -> type[BaseHTTPRequestHandler]:
    class _H(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path == "/api/trace":
                raw = list(capture.rows)
                rows = _filtered_trace_rows(raw, max_out=_MAX_TRACE_SERVE)
                _send_json(self, {"rows": rows})
                return
            if path == "/api/pag-slice":
                qs = parse_qs(parsed.query)
                ns_list = qs.get("namespace") or []
                ns = str(ns_list[0] if ns_list else "").strip()
                if not ns:
                    ns = namespace.strip()
                off_raw = (qs.get("node_offset") or ["0"])[0]
                try:
                    noff = max(0, int(str(off_raw)))
                except ValueError:
                    noff = 0
                try:
                    from ailit_cli.memory_cli import _pag_slice_payload
                    from agent_memory.pag_indexer import PagIndexer
                    from agent_memory.pag_slice_caps import (
                        PAG_SLICE_MAX_EDGES,
                        PAG_SLICE_MAX_NODES,
                    )

                    db = (
                        db_path.resolve()
                        if db_path is not None and db_path.is_file()
                        else PagIndexer.default_db_path()
                    )
                    if not db.is_file():
                        pl: dict[str, Any] = {
                            "ok": False,
                            "kind": "ailit_pag_graph_slice_v1",
                            "code": "missing_db",
                            "error": f"sqlite not found: {db}",
                            "namespace": ns,
                        }
                    else:
                        pl = _pag_slice_payload(
                            namespace=ns,
                            db_path=db,
                            level=None,
                            node_limit=min(80, PAG_SLICE_MAX_NODES),
                            node_offset=noff,
                            edge_limit=min(120, PAG_SLICE_MAX_EDGES),
                            edge_offset=0,
                        )
                except Exception as exc:
                    pl = {
                        "ok": False,
                        "error": str(exc),
                        "namespace": ns,
                    }
                _send_json(self, pl)
                return
            if path != "/":
                self.send_error(404)
                return
            index = _STATIC_DIR / "index.html"
            if not index.is_file():
                msg = b"memory viz: static index.html missing"
                self.send_response(500)
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
            data = index.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return _H
