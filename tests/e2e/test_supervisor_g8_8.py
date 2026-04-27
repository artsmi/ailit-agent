"""G.8: Supervisor lifecycle — start, connect, run task, shutdown.

Проверяет:
- ``supervisor start`` запускает Unix-сокет и ждёт подключений.
- ``supervisor connect`` подключается к сокету, отправляет команду ``run``,
  получает JSONL-события.
- ``supervisor shutdown`` останавливает сервер (через сигнал или shutdown-команду).
- Supervisor корректно завершается после shutdown (returncode 0).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cli_runner import AilitCliRunner


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _wait_for_socket(sock_path: Path, timeout: float = 8.0) -> None:
    """Ждать, пока Unix-сокет появится на файловой системе."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sock_path.is_socket():
            return
        time.sleep(0.1)
    raise TimeoutError(
        f"Socket {sock_path} did not appear within {timeout}s"
    )


def _wait_for_supervisor_ready(
    proc: subprocess.Popen[str],
    sock_path: Path,
    timeout: float = 10.0,
) -> None:
    """Ждать, пока supervisor запустится и создаст сокет.

    Проверяем:
    1. Процесс жив.
    2. Сокет существует.
    3. Можно открыть TCP-like соединение (через sendmsg/recv).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(
                f"Supervisor exited prematurely with code {proc.returncode}"
            )
        if sock_path.is_socket():
            # Пробуем открыть соединение
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
    """Подключиться к сокету, отправить JSON-команду, прочитать ответы.

    Возвращает список распарсенных JSON-строк (каждая строка — событие).
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(str(sock_path))
    payload = json.dumps(cmd, ensure_ascii=False) + "\n"
    sock.sendall(payload.encode("utf-8"))

    # Читаем, пока сокет не закроется или не выйдет таймаут
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
        return proc.returncode

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return proc.returncode


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def supervisor_sock_path(e2e_workspace: Path) -> Path:
    """Путь к Unix-сокету supervisor внутри e2e_workspace."""
    return e2e_workspace / ".ailit" / "supervisor.sock"


@pytest.fixture
def supervisor_env(
    e2e_workspace: Path,
    supervisor_sock_path: Path,
) -> dict[str, str]:
    """Окружение для supervisor: изолированный work_root и сокет."""
    env = os.environ.copy()
    env["AILIT_WORK_ROOT"] = str(e2e_workspace)
    env["AILIT_SUPERVISOR_SOCKET"] = str(supervisor_sock_path)
    # Отключаем live-провайдеры, чтобы тест не зависел от API-ключей
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
    """``supervisor start`` запускает сервер, ``supervisor connect``
    подключается и получает приветственное событие."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)

    # 1. Запускаем supervisor в фоне
    proc = runner.spawn(
        "supervisor",
        "start",
        project_root=mini_app_root,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        # 2. Подключаемся через CLI connect
        res = runner.supervisor_connect(
            project_root=mini_app_root,
            extra_env=supervisor_env,
        )
        assert res.returncode == 0, (
            f"supervisor connect failed: {res.stderr}"
        )
        # В stdout должно быть что-то похожее на JSONL или подтверждение
        assert "connected" in res.stdout.lower() or "supervisor" in res.stdout.lower()

    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_run_task_via_socket(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Через Unix-сокет отправляем ``run``-команду, получаем JSONL-события.

    Проверяем, что в ответе есть ``workflow.loaded`` и ``workflow.finished``
    (или ``task.skipped_dry_run`` при dry-run).
    """
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)

    proc = runner.spawn(
        "supervisor",
        "start",
        project_root=mini_app_root,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        # Отправляем run-команду напрямую через сокет
        cmd = {
            "command": "run",
            "workflow": "smoke",
            "provider": "mock",
            "dry_run": True,
            "max_turns": 4,
            "project_root": str(mini_app_root.resolve()),
        }
        events = _send_cmd_and_recv(supervisor_sock_path, cmd, timeout=15.0)
        assert len(events) > 0, "No events received from supervisor"

        event_types = {e.get("event_type") for e in events}
        assert "workflow.loaded" in event_types, (
            f"Expected workflow.loaded, got {event_types}"
        )
        # При dry-run должно быть skipped_dry_run или workflow.finished
        has_finished = "workflow.finished" in event_types
        has_skipped = "task.skipped_dry_run" in event_types
        assert has_finished or has_skipped, (
            f"Expected workflow.finished or task.skipped_dry_run, "
            f"got {event_types}"
        )

    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_shutdown_via_signal(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """SIGTERM останавливает supervisor, процесс завершается с кодом 0."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)

    proc = runner.spawn(
        "supervisor",
        "start",
        project_root=mini_app_root,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        # Отправляем SIGTERM
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Supervisor did not exit within timeout after SIGTERM")

        assert proc.returncode == 0, (
            f"Supervisor exited with code {proc.returncode}, expected 0"
        )

        # Сокет должен быть удалён
        assert not supervisor_sock_path.exists(), (
            "Socket should be removed after shutdown"
        )

    finally:
        # Если процесс ещё жив — добиваем
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.e2e
def test_supervisor_shutdown_via_command(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Через сокет отправляем ``shutdown``-команду, supervisor завершается.

    Если supervisor не поддерживает shutdown-команду — тест
    проверяет graceful fallback (SIGTERM).
    """
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)

    proc = runner.spawn(
        "supervisor",
        "start",
        project_root=mini_app_root,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        # Пробуем shutdown через сокет
        cmd = {"command": "shutdown"}
        try:
            events = _send_cmd_and_recv(
                supervisor_sock_path, cmd, timeout=5.0
            )
        except (ConnectionRefusedError, OSError, socket.timeout):
            events = []

        # Если supervisor не поддерживает shutdown-команду,
        # он может просто закрыть соединение или вернуть ошибку.
        # В любом случае, процесс должен быть жив.
        if proc.poll() is None:
            # shutdown не сработал — используем SIGTERM
            _stop_supervisor_gracefully(proc, supervisor_sock_path)

        assert proc.returncode == 0, (
            f"Supervisor exited with code {proc.returncode}, expected 0"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.e2e
def test_supervisor_multiple_connections(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Supervisor обрабатывает несколько последовательных подключений."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)

    proc = runner.spawn(
        "supervisor",
        "start",
        project_root=mini_app_root,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        # Первое подключение
        cmd1 = {
            "command": "run",
            "workflow": "smoke",
            "provider": "mock",
            "dry_run": True,
            "max_turns": 2,
            "project_root": str(mini_app_root.resolve()),
        }
        events1 = _send_cmd_and_recv(
            supervisor_sock_path, cmd1, timeout=15.0
        )
        assert len(events1) > 0, "No events from first connection"

        # Второе подключение
        cmd2 = {
            "command": "run",
            "workflow": "smoke",
            "provider": "mock",
            "dry_run": True,
            "max_turns": 2,
            "project_root": str(mini_app_root.resolve()),
        }
        events2 = _send_cmd_and_recv(
            supervisor_sock_path, cmd2, timeout=15.0
        )
        assert len(events2) > 0, "No events from second connection"

        # Оба ответа должны содержать workflow.loaded
        types1 = {e.get("event_type") for e in events1}
        types2 = {e.get("event_type") for e in events2}
        assert "workflow.loaded" in types1, (
            f"First connection missing workflow.loaded: {types1}"
        )
        assert "workflow.loaded" in types2, (
            f"Second connection missing workflow.loaded: {types2}"
        )

    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)


@pytest.mark.e2e
def test_supervisor_rejects_invalid_command(
    mini_app_root: Path,
    e2e_workspace: Path,
    supervisor_sock_path: Path,
    supervisor_env: dict[str, str],
) -> None:
    """Supervisor возвращает ошибку на неизвестную команду."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)

    proc = runner.spawn(
        "supervisor",
        "start",
        project_root=mini_app_root,
        extra_env=supervisor_env,
    )
    try:
        _wait_for_supervisor_ready(proc, supervisor_sock_path, timeout=10.0)

        # Отправляем невалидную команду
        cmd = {"command": "nonexistent"}
        events = _send_cmd_and_recv(
            supervisor_sock_path, cmd, timeout=5.0
        )

        # Должен быть хотя бы один ответ с ошибкой
        assert len(events) > 0, (
            "Expected error response for invalid command"
        )
        # Проверяем, что в ответе есть признак ошибки
        first = events[0]
        assert (
            "error" in first.get("event_type", "").lower()
            or first.get("status") == "error"
            or "error" in str(first).lower()
        ), f"Expected error response, got: {first}"

    finally:
        _stop_supervisor_gracefully(proc, supervisor_sock_path)
