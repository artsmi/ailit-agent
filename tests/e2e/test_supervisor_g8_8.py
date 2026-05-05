"""G.8: Supervisor — `ailit runtime supervisor`, сокет, status, broker.

Соответствует ``_dispatch_cmd`` (поле ``cmd``, не ``command``):
status, brokers, create_or_get_broker, stop_broker.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from cli_runner import AilitCliRunner


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _runtime_ailit_dir(e2e_workspace: Path) -> Path:
    """Каталог runtime (содержит ``supervisor.sock``)."""
    return e2e_workspace / ".ailit"


def _wait_for_socket(sock_path: Path, timeout: float = 8.0) -> None:
    """Ждать, пока Unix-сокет появится на файловой системе."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sock_path.is_socket():
            return
        time.sleep(0.1)
    msg = f"Socket {sock_path} did not appear within {timeout}s"
    raise TimeoutError(msg)


def _wait_for_supervisor_ready(
    proc: subprocess.Popen[str],
    sock_path: Path,
    timeout: float = 10.0,
) -> None:
    """Ждать, пока supervisor запустится и создаст сокет.

    Проверяем:
    1. Процесс жив.
    2. Сокет существует.
    3. Можно открыть соединение.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate()
            details = f"stdout={out!r} stderr={err!r}"
            pytest.fail(
                f"Supervisor exited prematurely with code {proc.returncode} "
                f"({details})"
            )
        if sock_path.is_socket():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect(str(sock_path))
                sock.close()
                return
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                pass
        time.sleep(0.2)
    pytest.fail(f"Supervisor did not become ready within {timeout}s")


def _send_cmd_and_recv(
    sock_path: Path,
    cmd: dict,
    timeout: float = 5.0,
) -> list[dict]:
    """Отправить JSON (один запрос) и прочитать JSON-строки ответа."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(str(sock_path))
    payload = json.dumps(cmd, ensure_ascii=False) + "\n"
    sock.sendall(payload.encode("utf-8"))

    lines: list[dict] = []
    buf = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    lines.append(json.loads(line.decode("utf-8")))
    except socket.timeout:
        pass
    finally:
        sock.close()
    return lines


def _stop_supervisor_gracefully(
    proc: subprocess.Popen[str],
    sock_path: Path,
    timeout: float = 8.0,
) -> int:
    """Пытаемся остановить supervisor через SIGTERM, ждём завершения.

    Если процесс не завершился за timeout — SIGKILL.
    """
    if proc.poll() is not None:
        return int(proc.returncode) if proc.returncode is not None else -1

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return int(proc.returncode) if proc.returncode is not None else -1


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def supervisor_sock_path(e2e_workspace: Path) -> Path:
    """Путь к Unix-сокету supervisor внутри e2e_workspace."""
    return _runtime_ailit_dir(e2e_workspace) / "supervisor.sock"


@pytest.fixture
def supervisor_env(
    e2e_workspace: Path,
    supervisor_sock_path: Path,
) -> dict[str, str]:
    """Окружение: изолированный runtime и согласованные пути сокета."""
    env = os.environ.copy()
    env["AILIT_WORK_ROOT"] = str(e2e_workspace)
    # Используется ``default_runtime_dir()`` в коде без явного --runtime-dir
    rt = _runtime_ailit_dir(e2e_workspace)
    env["AILIT_RUNTIME_DIR"] = str(rt)
    # Legacy для тестов, смотревших кастомный путь
    env["AILIT_SUPERVISOR_SOCKET"] = str(supervisor_sock_path)
    env.setdefault("AILIT_CONFIG_DIR", str(e2e_workspace / "ailit_config"))
    cfg_dir = Path(env["AILIT_CONFIG_DIR"])
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "live:\n  run: false\n",
        encoding="utf-8",
    )
    return env


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_supervisor_start_and_connect(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Поднять `runtime supervisor` и проверить `runtime status` по сокету."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    rt = _runtime_ailit_dir(e2e_workspace)

    proc = runner.spawn(
        "runtime",
        "supervisor",
        "--runtime-dir",
        str(rt.resolve()),
        project_root=None,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        res = runner.runtime_status(
            runtime_dir=rt,
            extra_env=supervisor_env,
        )
        err_msg = f"runtime status: {res.stderr!r} {res.stdout!r}"
        assert res.returncode == 0, err_msg
        out = (res.stdout or "").lower()
        assert "runtime_dir" in out and "ok" in out
    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_status_via_socket(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Через Unix-сокет: ``{"cmd": "status"}`` возвращает ok и сводку."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    rt = _runtime_ailit_dir(e2e_workspace)

    proc = runner.spawn(
        "runtime",
        "supervisor",
        "--runtime-dir",
        str(rt.resolve()),
        project_root=None,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        lines = _send_cmd_and_recv(
            supervisor_sock_path,
            {"cmd": "status"},
            timeout=5.0,
        )
        assert len(lines) >= 1, lines
        first = lines[0]
        assert first.get("ok") is True
        assert "result" in first
        res = first["result"]
        assert "runtime_dir" in res
    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_shutdown_via_signal(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """SIGTERM останавливает supervisor, процесс завершается."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    rt = _runtime_ailit_dir(e2e_workspace)

    proc = runner.spawn(
        "runtime",
        "supervisor",
        "--runtime-dir",
        str(rt.resolve()),
        project_root=None,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Supervisor did not exit after SIGTERM")

        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.e2e
def test_supervisor_broker_create_via_socket(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """``create_or_get_broker`` через сокет (без workflow-раннера)."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    rt = _runtime_ailit_dir(e2e_workspace)

    proc = runner.spawn(
        "runtime",
        "supervisor",
        "--runtime-dir",
        str(rt.resolve()),
        project_root=None,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        lines = _send_cmd_and_recv(
            supervisor_sock_path,
            {
                "cmd": "create_or_get_broker",
                "chat_id": "e2e-smoke",
                "namespace": "ns",
                "project_root": str(mini_app_root.resolve()),
            },
            timeout=30.0,
        )
        assert len(lines) >= 1, lines
        first = lines[0]
        assert first.get("ok") is True
        result = first.get("result")
        assert isinstance(result, dict)
        assert result.get("chat_id") == "e2e-smoke"
    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_broker_create_with_workspace_tc_py_sup_01(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """TC-PY-SUP-01: primary + workspace из одного элемента, ok и endpoint."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    rt = _runtime_ailit_dir(e2e_workspace)
    extra_root = (e2e_workspace / "ws_extra").resolve()
    extra_root.mkdir(parents=True, exist_ok=True)

    proc = runner.spawn(
        "runtime",
        "supervisor",
        "--runtime-dir",
        str(rt.resolve()),
        project_root=None,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        lines = _send_cmd_and_recv(
            supervisor_sock_path,
            {
                "cmd": "create_or_get_broker",
                "chat_id": "e2e-ws",
                "primary_namespace": "pns",
                "primary_project_root": str(mini_app_root.resolve()),
                "workspace": [
                    {
                        "namespace": "sns",
                        "project_root": str(extra_root),
                    },
                ],
            },
            timeout=30.0,
        )
        assert len(lines) >= 1, lines
        first = lines[0]
        assert first.get("ok") is True
        result = first.get("result")
        assert isinstance(result, dict)
        assert result.get("chat_id") == "e2e-ws"
        ws = result.get("workspace")
        assert isinstance(ws, list) and len(ws) == 1
        ep = str(result.get("endpoint", "") or "")
        assert ep.startswith("unix://")
    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_multiple_status_requests(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Несколько последовательных запросов status по одному сокету-серверу."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    rt = _runtime_ailit_dir(e2e_workspace)

    proc = runner.spawn(
        "runtime",
        "supervisor",
        "--runtime-dir",
        str(rt.resolve()),
        project_root=None,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        for _ in range(2):
            lines = _send_cmd_and_recv(
                supervisor_sock_path,
                {"cmd": "status"},
                timeout=5.0,
            )
            assert len(lines) >= 1
            assert lines[0].get("ok") is True
    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_rejects_invalid_cmd(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Неизвестный ``cmd`` даёт ok: false и поле error."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    rt = _runtime_ailit_dir(e2e_workspace)

    proc = runner.spawn(
        "runtime",
        "supervisor",
        "--runtime-dir",
        str(rt.resolve()),
        project_root=None,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        lines = _send_cmd_and_recv(
            supervisor_sock_path,
            {"cmd": "nonexistent_command_xyz"},
            timeout=5.0,
        )
        assert len(lines) == 1, lines
        first = lines[0]
        assert first.get("ok") is False
        err = first.get("error")
        assert isinstance(err, dict)
    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)
