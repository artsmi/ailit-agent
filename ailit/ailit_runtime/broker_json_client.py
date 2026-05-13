"""G20.2: клиент JSON-lines для AgentBroker и supervisor (разрешение endpoint).

Транспорт совпадает с ``tests/runtime/test_broker_routing.py`` и
``ailit_runtime.broker._BrokerHandler``: одна строка JSON + ``\\n`` на RPC;
для live-trace отдельное соединение с первой строкой
``{"cmd":"subscribe_trace"}``.
"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping

from ailit_runtime.errors import RuntimeProtocolError
from ailit_runtime.paths import RuntimePaths
from ailit_runtime.supervisor import supervisor_request

_SUBSCRIBE_TRACE_LINE: Final[bytes] = (
    json.dumps({"cmd": "subscribe_trace"}, separators=(",", ":")).encode(
        "utf-8",
    )
    + b"\n"
)


class BrokerTransportError(OSError):
    """Ошибка сокета при работе с broker."""


class BrokerResponseError(RuntimeError):
    """Пустой ответ, таймаут или невалидный JSON от broker."""


def encode_json_line(obj: Mapping[str, Any]) -> bytes:
    """Сериализовать объект в одну строку JSON + newline (broker RPC)."""
    raw = json.dumps(dict(obj), ensure_ascii=False, separators=(",", ":"))
    if "\n" in raw or "\r" in raw:
        raise RuntimeProtocolError(
            code="invalid_envelope",
            message="envelope json must be single-line",
        )
    return raw.encode("utf-8") + b"\n"


def decode_json_line(line: str) -> dict[str, Any]:
    """Разобрать одну строку ответа supervisor/broker."""
    stripped = line.strip()
    if not stripped:
        raise BrokerResponseError("empty response line")
    try:
        out = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise BrokerResponseError(f"invalid json: {exc}") from exc
    if not isinstance(out, dict):
        raise BrokerResponseError("response must be a JSON object")
    return out


def unix_path_from_broker_endpoint(endpoint: str) -> Path:
    """Преобразовать ``unix://…`` из registry supervisor в ``Path``."""
    ep = str(endpoint or "").strip()
    if not ep.startswith("unix://"):
        raise RuntimeProtocolError(
            code="invalid_broker_endpoint",
            message=f"expected unix:// endpoint, got {ep!r}",
        )
    tail = ep.removeprefix("unix://").strip()
    if not tail:
        raise RuntimeProtocolError(
            code="invalid_broker_endpoint",
            message="empty path after unix://",
        )
    return Path(tail)


def wait_for_path(
    path: Path,
    *,
    exists_timeout_s: float,
    poll_s: float = 0.05,
) -> None:
    """Дождаться появления пути (например сокета broker после spawn)."""
    deadline = time.monotonic() + max(0.01, exists_timeout_s)
    while time.monotonic() < deadline:
        if path.exists() and path.is_socket():
            return
        time.sleep(poll_s)
    raise BrokerTransportError(f"socket path not ready: {path}")


def resolve_broker_socket_for_cli(
    *,
    explicit_socket: Path | None,
    runtime_dir: Path,
    broker_chat_id: str,
    supervisor_timeout_s: float = 5.0,
) -> Path:
    """D4: путь к Unix-сокету broker — явный или из supervisor ``brokers``."""
    if explicit_socket is not None:
        p = explicit_socket.expanduser().resolve()
        return p
    cid = str(broker_chat_id or "").strip()
    if not cid:
        raise RuntimeProtocolError(
            code="missing_broker_chat_id",
            message="broker_chat_id required when explicit_socket is omitted",
        )
    paths = RuntimePaths(runtime_dir=runtime_dir.expanduser().resolve())
    sup_sock = paths.supervisor_socket
    if not sup_sock.exists():
        raise RuntimeProtocolError(
            code="supervisor_unavailable",
            message=(
                f"supervisor socket not found: {sup_sock}. "
                "Start `ailit runtime supervisor` or set --broker-socket."
            ),
        )
    raw = supervisor_request(
        socket_path=sup_sock,
        request={"cmd": "brokers"},
        timeout_s=supervisor_timeout_s,
    )
    if raw.get("ok") is not True:
        err = raw.get("error")
        msg = err if isinstance(err, str) else str(err)
        raise RuntimeProtocolError(
            code="supervisor_brokers_failed",
            message=msg or "brokers cmd failed",
        )
    result = raw.get("result")
    if not isinstance(result, dict):
        raise RuntimeProtocolError(
            code="supervisor_brokers_shape",
            message="brokers response.result must be dict",
        )
    brokers = result.get("brokers")
    if not isinstance(brokers, list):
        raise RuntimeProtocolError(
            code="supervisor_brokers_shape",
            message="result.brokers must be list",
        )
    for row in brokers:
        if not isinstance(row, dict):
            continue
        if str(row.get("chat_id", "") or "").strip() != cid:
            continue
        ep = str(row.get("endpoint", "") or "").strip()
        return unix_path_from_broker_endpoint(ep).resolve()
    raise RuntimeProtocolError(
        code="broker_not_found",
        message=(
            f"no broker with chat_id={cid!r} in supervisor registry "
            f"({sup_sock})"
        ),
    )


def stable_memory_cli_broker_chat_id(
    *,
    project_root: Path,
    namespace: str,
) -> str:
    """Стабильный короткий ``chat_id`` для CLI (D8, G20, sun_path лимит)."""
    pr = project_root.expanduser().resolve()
    key = f"{pr}:{namespace}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()[:12]
    return f"c{digest}"


def create_or_get_broker_via_supervisor(
    *,
    runtime_dir: Path,
    chat_id: str,
    primary_namespace: str,
    primary_project_root: Path,
    supervisor_create_timeout_s: float = 60.0,
    broker_socket_ready_s: float = 15.0,
) -> Path:
    """Вызвать supervisor ``create_or_get_broker`` и дождаться Unix-сокета."""
    paths = RuntimePaths(runtime_dir=runtime_dir.expanduser().resolve())
    sup_sock = paths.supervisor_socket
    if not sup_sock.exists():
        raise RuntimeProtocolError(
            code="supervisor_unavailable",
            message=(
                f"supervisor socket not found: {sup_sock}. "
                "Start `ailit runtime supervisor` or set --broker-socket."
            ),
        )
    pn = str(primary_namespace or "").strip()
    pp = primary_project_root.expanduser().resolve()
    if not pn:
        raise RuntimeProtocolError(
            code="invalid_args",
            message="primary_namespace required for create_or_get_broker",
        )
    raw = supervisor_request(
        socket_path=sup_sock,
        request={
            "cmd": "create_or_get_broker",
            "chat_id": str(chat_id or "").strip(),
            "primary_namespace": pn,
            "primary_project_root": str(pp),
        },
        timeout_s=supervisor_create_timeout_s,
    )
    if raw.get("ok") is not True:
        err = raw.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("code") or err)
        else:
            msg = err if isinstance(err, str) else str(err)
        raise RuntimeProtocolError(
            code="supervisor_create_broker_failed",
            message=msg or "create_or_get_broker failed",
        )
    result = raw.get("result")
    if not isinstance(result, dict):
        raise RuntimeProtocolError(
            code="supervisor_create_broker_shape",
            message="create_or_get_broker result must be dict",
        )
    ep = str(result.get("endpoint", "") or "").strip()
    sock_path = unix_path_from_broker_endpoint(ep).resolve()
    wait_for_path(sock_path, exists_timeout_s=broker_socket_ready_s)
    return sock_path


def resolve_or_ensure_broker_socket_for_cli(
    *,
    explicit_socket: Path | None,
    runtime_dir: Path,
    broker_chat_id: str | None,
    primary_namespace: str,
    primary_project_root: Path,
    allow_auto_chat_id: bool = True,
    supervisor_brokers_timeout_s: float = 5.0,
    supervisor_create_timeout_s: float = 60.0,
    broker_socket_ready_s: float = 15.0,
) -> tuple[Path, str]:
    """Разрешить сокет broker.

    Если записи в registry нет, вызывается ``create_or_get_broker``.
    """
    pr = primary_project_root.expanduser().resolve()
    pn = str(primary_namespace or "").strip()
    if not pn:
        raise RuntimeProtocolError(
            code="memory_cli_namespace_required",
            message="PAG namespace is empty; cannot resolve broker",
        )
    cid_in = str(broker_chat_id or "").strip()
    if explicit_socket is not None:
        p = explicit_socket.expanduser().resolve()
        if not cid_in:
            raise RuntimeProtocolError(
                code="missing_broker_chat_id",
                message=(
                    "--broker-chat-id required when --broker-socket is set"
                ),
            )
        return p, cid_in
    cid = cid_in
    if not cid:
        if not allow_auto_chat_id:
            raise RuntimeProtocolError(
                code="missing_broker_chat_id",
                message=(
                    "--broker-chat-id required when auto broker is disabled"
                ),
            )
        cid = stable_memory_cli_broker_chat_id(
            project_root=pr,
            namespace=pn,
        )
    rd = runtime_dir.expanduser().resolve()
    try:
        path = resolve_broker_socket_for_cli(
            explicit_socket=None,
            runtime_dir=rd,
            broker_chat_id=cid,
            supervisor_timeout_s=supervisor_brokers_timeout_s,
        )
        return path, cid
    except RuntimeProtocolError as exc:
        if exc.code != "broker_not_found":
            raise
    sock_path = create_or_get_broker_via_supervisor(
        runtime_dir=rd,
        chat_id=cid,
        primary_namespace=pn,
        primary_project_root=pr,
        supervisor_create_timeout_s=supervisor_create_timeout_s,
        broker_socket_ready_s=broker_socket_ready_s,
    )
    return sock_path, cid


@dataclass(slots=True)
class BrokerJsonRpcClient:
    """Один RPC на одно соединение (контракт ``_BrokerHandler``)."""

    socket_path: Path

    def ping(self, *, timeout_s: float = 2.0) -> str:
        """Отправить строку ``ping``, ожидать ``pong``."""
        sock = self._connected(timeout_s=timeout_s)
        try:
            sock.sendall(b"ping\n")
            line = self._read_text_line(sock, timeout_s=timeout_s)
        finally:
            sock.close()
        return line.strip()

    def call(
        self,
        envelope: Mapping[str, Any],
        *,
        timeout_s: float = 120.0,
    ) -> dict[str, Any]:
        """Отправить ``RuntimeRequestEnvelope`` и вернуть один JSON-object."""
        payload = encode_json_line(envelope)
        sock = self._connected(timeout_s=min(10.0, timeout_s))
        try:
            sock.settimeout(timeout_s)
            sock.sendall(payload)
            line = self._read_text_line(sock, timeout_s=timeout_s)
        finally:
            sock.close()
        return decode_json_line(line)

    def _connected(self, *, timeout_s: float) -> socket.socket:
        path = self.socket_path.expanduser().resolve()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)
        try:
            sock.connect(str(path))
        except OSError as exc:
            sock.close()
            raise BrokerTransportError(str(exc)) from exc
        return sock

    @staticmethod
    def _read_text_line(sock: socket.socket, *, timeout_s: float) -> str:
        sock.settimeout(timeout_s)
        chunks: list[bytes] = []
        while True:
            try:
                b = sock.recv(4096)
            except socket.timeout as exc:
                raise BrokerResponseError("read timeout") from exc
            if not b:
                break
            chunks.append(b)
            data = b"".join(chunks)
            if b"\n" in data:
                line, _rest = data.split(b"\n", 1)
                return line.decode("utf-8", errors="replace")
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if not text.strip():
            raise BrokerResponseError("empty response from broker")
        return text


_MAX_TRACE_BUFFER: Final[int] = 16 * 1024 * 1024


@dataclass
class BrokerTraceSubscriber:
    """Второе соединение: ``subscribe_trace`` и поток JSONL-строк trace."""

    socket_path: Path
    _sock: socket.socket | None = field(default=None, repr=False)
    _buf: bytearray = field(default_factory=bytearray, repr=False)

    def connect(self, *, connect_timeout_s: float = 5.0) -> None:
        """Подключиться и отправить команду подписки."""
        if self._sock is not None:
            return
        path = self.socket_path.expanduser().resolve()
        wait_for_path(path, exists_timeout_s=connect_timeout_s)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(connect_timeout_s)
        try:
            sock.connect(str(path))
            sock.sendall(_SUBSCRIBE_TRACE_LINE)
        except OSError as exc:
            sock.close()
            raise BrokerTransportError(str(exc)) from exc
        self._sock = sock

    def close(self) -> None:
        """Закрыть сокет подписчика."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._buf.clear()

    def read_object(
        self,
        *,
        timeout_s: float | None,
    ) -> dict[str, Any] | None:
        """Считать один JSON-object из потока; ``None`` при таймауте."""
        if self._sock is None:
            raise RuntimeError("BrokerTraceSubscriber.connect() first")
        self._sock.settimeout(timeout_s)
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                raw_line = bytes(self._buf[:nl])
                del self._buf[: nl + 1]
                text = raw_line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    return obj
                continue
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                return None
            except OSError:
                return None
            if not chunk:
                return None
            self._buf.extend(chunk)
            if len(self._buf) > _MAX_TRACE_BUFFER:
                raise BrokerResponseError("trace buffer overflow (no newline)")


class BrokerTraceBackgroundCapture:
    """Фоновый сбор trace-строк (удобно для тестов и CLI viz, G20.6)."""

    def __init__(self, socket_path: Path) -> None:
        self._path = socket_path.expanduser().resolve()
        self._subscriber = BrokerTraceSubscriber(self._path)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.rows: list[dict[str, Any]] = []

    @property
    def socket_path(self) -> Path:
        """Путь сокета broker."""
        return self._path

    def start(self, *, connect_timeout_s: float = 5.0) -> None:
        """Запустить поток, который копит объекты в ``rows``."""
        if self._thread is not None:
            return

        def _run() -> None:
            try:
                self._subscriber.connect(connect_timeout_s=connect_timeout_s)
            except OSError:
                return
            while not self._stop.is_set():
                row = self._subscriber.read_object(timeout_s=0.5)
                if row is None:
                    continue
                self.rows.append(row)

        self._thread = threading.Thread(
            target=_run,
            name="broker-trace-capture",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, join_timeout_s: float = 3.0) -> None:
        """Остановить поток и закрыть сокет."""
        self._stop.set()
        self._subscriber.close()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout_s)
            self._thread = None
        self._stop.clear()

    def wait_for_rows(
        self,
        *,
        min_count: int,
        timeout_s: float,
        poll_s: float = 0.05,
    ) -> None:
        """Дождаться, пока ``len(rows) >= min_count``."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if len(self.rows) >= min_count:
                return
            time.sleep(poll_s)
        raise BrokerResponseError(
            f"timeout: got {len(self.rows)} rows, need {min_count}",
        )


def call_on_trace_capture(
    socket_path: Path,
    envelope: Mapping[str, Any],
    *,
    rpc_timeout_s: float = 5.0,
    capture_wait_s: float = 2.0,
    min_trace_rows: int = 1,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """RPC под фоновым trace-capture (как в ``test_broker_routing``)."""
    cap = BrokerTraceBackgroundCapture(socket_path)
    cap.start(connect_timeout_s=min(5.0, capture_wait_s + 1.0))
    time.sleep(0.12)
    try:
        client = BrokerJsonRpcClient(socket_path)
        response = client.call(envelope, timeout_s=rpc_timeout_s)
        cap.wait_for_rows(min_count=min_trace_rows, timeout_s=capture_wait_s)
        return response, list(cap.rows)
    finally:
        cap.stop()
