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
    cancelled: bool
    truncated: bool
    spill_path: str | None


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

    def run(
        self,
        command: str,
        *,
        timeout_ms: int,
        max_capture_bytes: int,
    ) -> ShellSessionRunOutcome:
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
        used_bytes = 0
        timed_out = False
        cancelled = False
        truncated = False
        spill: str | None = None
        exit_code: int | None = None
        while True:
            from agent_core.tool_runtime.cancel_context import current_cancel

            ev = current_cancel()
            if ev is not None and ev.is_set():
                cancelled = True
                break
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
            if not truncated:
                b = len(line.encode("utf-8"))
                used_bytes += b
                if used_bytes > max_capture_bytes:
                    truncated = True
                    spill_dir = Path(str(os.getcwd())).resolve() / ".ailit"
                    try:
                        spill_dir.mkdir(parents=True, exist_ok=True)
                        spill_path = spill_dir / (
                            f"shell-session-spill-{uuid.uuid4().hex}.txt"
                        )
                        spill_path.write_text(
                            "".join(buf_parts),
                            encoding="utf-8",
                            errors="replace",
                        )
                        spill = str(spill_path)
                    except OSError:
                        spill = None
                else:
                    buf_parts.append(line)
            else:
                # При превышении лимита мы уже "срезаем" вывод в UI; spill-файл
                # отражает вывод до момента truncation (безопасный минимум).
                pass
        if timed_out:
            exit_code = None
            self.dispose()
        if cancelled:
            exit_code = None
            self.dispose()
        return ShellSessionRunOutcome(
            exit_code=exit_code,
            combined_output="".join(buf_parts),
            timed_out=timed_out,
            cancelled=cancelled,
            truncated=truncated,
            spill_path=spill,
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
        self._seq: dict[str, int] = {}

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
        self._seq = {}

    def reset(self, session_key: str) -> None:
        """Сбросить (перезапустить) конкретную сессию."""
        sess = self._sessions.pop(session_key, None)
        if sess is not None:
            sess.dispose()
        self._seq.pop(session_key, None)

    def next_seq(self, session_key: str) -> int:
        """Монотонный счётчик команд в сессии (для UI/событий)."""
        cur = int(self._seq.get(session_key, 0))
        nxt = cur + 1
        self._seq[session_key] = nxt
        return nxt

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
_DEFAULT_MANAGER_CFG: tuple[int, int] | None = None


def default_shell_session_manager() -> ShellSessionManager:
    """Глобальный singleton менеджера сессий."""
    global _DEFAULT_MANAGER  # noqa: PLW0603
    global _DEFAULT_MANAGER_CFG  # noqa: PLW0603
    max_s = 16
    idle_ms = 10 * 60 * 1000
    raw_max = os.environ.get("AILIT_BASH_SESSION_MAX_SESSIONS")
    raw_idle = os.environ.get("AILIT_BASH_SESSION_IDLE_TIMEOUT_MS")
    if raw_max is not None and str(raw_max).strip() != "":
        max_s = max(1, int(raw_max))
    if raw_idle is not None and str(raw_idle).strip() != "":
        idle_ms = max(1, int(raw_idle))
    cfg = (max_s, idle_ms)
    if _DEFAULT_MANAGER is None or _DEFAULT_MANAGER_CFG != cfg:
        if _DEFAULT_MANAGER is not None:
            _DEFAULT_MANAGER.dispose_all()
        _DEFAULT_MANAGER = ShellSessionManager(
            max_sessions=max_s,
            idle_timeout_ms=idle_ms,
        )
        _DEFAULT_MANAGER_CFG = cfg
    return _DEFAULT_MANAGER
