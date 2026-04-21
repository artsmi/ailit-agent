"""Долгоживущая shell-сессия для chat/TUI (этап H стратегии).

MVP: один процесс bash, общение через stdin/stdout.
Для отделения вывода одной команды от другой используется уникальный маркер.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True, slots=True)
class ShellSessionRunOutcome:
    """Результат одной команды в сессионном shell."""

    exit_code: int | None
    combined_output: str
    timed_out: bool


class BashSessionHandle:
    """Один процесс bash, который живёт между вызовами."""

    _READ_CHUNK: Final[int] = 4096

    def __init__(self, *, cwd: Path, env: dict[str, str]) -> None:
        """Запустить bash, готовый принимать команды через stdin."""
        bash = os.environ.get("SHELL") or "bash"
        self._proc = subprocess.Popen(
            [bash, "--noprofile", "--norc"],
            cwd=str(cwd.resolve()),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("bash session: missing pipes")
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout
        self._last_used_ts = time.time()

    @property
    def last_used_ts(self) -> float:
        """Unix timestamp последнего использования."""
        return float(self._last_used_ts)

    def is_alive(self) -> bool:
        """True если процесс ещё жив."""
        return self._proc.poll() is None

    def dispose(self) -> None:
        """Завершить процесс."""
        if self._proc.poll() is not None:
            return
        try:
            self._proc.kill()
        except OSError:
            pass

    def run(self, command: str, *, timeout_ms: int) -> ShellSessionRunOutcome:
        """Выполнить команду в текущей сессии и вернуть вывод до маркера."""
        if not self.is_alive():
            raise RuntimeError("bash session is not running")
        if "\n" in command or "\r" in command:
            raise ValueError(
                "session shell: multiline commands are not supported",
            )
        marker = f"__AILIT_END__{uuid.uuid4().hex}__"
        script = f"{command}\necho {marker}:$?\n"
        self._stdin.write(script)
        self._stdin.flush()
        self._last_used_ts = time.time()

        deadline = time.time() + (timeout_ms / 1000.0)
        buf_parts: list[str] = []
        timed_out = False
        exit_code: int | None = None
        while True:
            if time.time() > deadline:
                timed_out = True
                break
            line = self._stdout.readline()
            if line == "":
                break
            if line.startswith(marker):
                tail = line.strip().split(":", maxsplit=1)
                if len(tail) == 2:
                    try:
                        exit_code = int(tail[1])
                    except ValueError:
                        exit_code = None
                break
            buf_parts.append(line)
        if timed_out:
            exit_code = None
        return ShellSessionRunOutcome(
            exit_code=exit_code,
            combined_output="".join(buf_parts),
            timed_out=timed_out,
        )


class ShellSessionManager:
    """Глобальный менеджер сессий bash в текущем процессе."""

    def __init__(
        self,
        *,
        max_sessions: int = 16,
        idle_timeout_ms: int = 10 * 60 * 1000,
    ) -> None:
        """Создать менеджер."""
        self._max_sessions = int(max_sessions)
        self._idle_timeout_ms = int(idle_timeout_ms)
        self._sessions: dict[str, BashSessionHandle] = {}

    def _cleanup_idle(self) -> None:
        now = time.time()
        idle_sec = self._idle_timeout_ms / 1000.0
        dead: list[str] = []
        for key, sess in self._sessions.items():
            if not sess.is_alive():
                dead.append(key)
                continue
            if now - sess.last_used_ts > idle_sec:
                sess.dispose()
                dead.append(key)
        for key in dead:
            self._sessions.pop(key, None)

    def dispose_all(self) -> None:
        """Завершить все сессии."""
        for sess in self._sessions.values():
            sess.dispose()
        self._sessions = {}

    def reset(self, session_key: str) -> None:
        """Сбросить (перезапустить) конкретную сессию."""
        sess = self._sessions.pop(session_key, None)
        if sess is not None:
            sess.dispose()

    def get_or_create(
        self,
        session_key: str,
        *,
        cwd: Path,
    ) -> BashSessionHandle:
        """Вернуть живую сессию или создать новую."""
        self._cleanup_idle()
        cur = self._sessions.get(session_key)
        if cur is not None and cur.is_alive():
            return cur
        if len(self._sessions) >= self._max_sessions:
            # Сбросить самую старую по last_used_ts.
            oldest = min(
                self._sessions.items(),
                key=lambda kv: kv[1].last_used_ts,
            )[0]
            self.reset(oldest)
        env = dict(os.environ)
        sess = BashSessionHandle(cwd=cwd, env=env)
        self._sessions[session_key] = sess
        return sess


_DEFAULT_MANAGER: ShellSessionManager | None = None


def default_shell_session_manager() -> ShellSessionManager:
    """Глобальный singleton менеджера сессий."""
    global _DEFAULT_MANAGER  # noqa: PLW0603
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = ShellSessionManager()
    return _DEFAULT_MANAGER
