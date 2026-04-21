"""Фоновый прогон одного хода ailit chat с возможностью stop."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from agent_core.models import ChatMessage
from agent_core.session.loop import (
    SessionOutcome,
    SessionRunner,
    SessionSettings,
)
from agent_core.tool_runtime.approval import ApprovalSession


@dataclass(slots=True)
class ChatStopWorkerState:
    """Разделяемое состояние для UI-потока."""

    started: bool = False
    finished: bool = False
    cancelled: bool = False
    error: str | None = None
    assistant_text: str = ""
    status_line: str = ""
    events: tuple[dict[str, Any], ...] = ()
    outcome: SessionOutcome | None = None
    bash_executions: list[dict[str, Any]] = field(default_factory=list)
    file_change_lines: list[str] = field(default_factory=list)


class ChatStopWorker:
    """Thread worker: SessionRunner.run + сбор событий, stop через Event."""

    def __init__(
        self,
        *,
        runner: SessionRunner,
        runner_messages: list[ChatMessage],
        settings: SessionSettings,
        diag_sink: Any,
    ) -> None:
        self._runner = runner
        self._messages = list(runner_messages)
        self._settings = settings
        self._diag_sink = diag_sink
        self.cancel_event = threading.Event()
        self.state = ChatStopWorkerState()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Запустить worker (один раз)."""
        with self._lock:
            if self.state.started:
                return
            self.state.started = True
        self._thread.start()

    def is_alive(self) -> bool:
        """True если поток ещё работает."""
        return self._thread.is_alive()

    def request_cancel(self) -> None:
        """Попросить отменить прогон."""
        self.cancel_event.set()

    def _run(self) -> None:
        live: list[str] = []
        file_changes: list[str] = []
        bash_execs: list[dict[str, Any]] = []

        def on_event(ev: object) -> None:
            et = getattr(ev, "type", "")
            payload = getattr(ev, "payload", {})
            if et == "assistant.delta" and isinstance(payload, dict):
                txt = payload.get("text")
                if isinstance(txt, str) and txt:
                    live.append(txt)
                    with self._lock:
                        self.state.assistant_text = "".join(live)
                return
            if et == "tool.call_finished" and isinstance(payload, dict):
                t = payload.get("tool")
                ok = payload.get("ok")
                rp = payload.get("relative_path")
                fk = payload.get("file_change_kind")
                if (
                    ok is True
                    and t == "write_file"
                    and isinstance(rp, str)
                    and fk in ("created", "updated")
                ):
                    sym = "+" if fk == "created" else "~"
                    file_changes.append(f"{sym} `{rp}` ({fk})")
                    with self._lock:
                        self.state.file_change_lines = list(file_changes)
                return
            if et == "bash.execution" and isinstance(payload, dict):
                bash_execs.append(dict(payload))
                with self._lock:
                    self.state.bash_executions = list(bash_execs)
                return
            if et == "tool.call_started" and isinstance(payload, dict):
                tn = payload.get("tool")
                if isinstance(tn, str) and tn.strip():
                    with self._lock:
                        name = tn.strip()
                        self.state.status_line = f"Шаг: {name}"
                return

        try:
            out = self._runner.run(
                self._messages,
                ApprovalSession(),
                self._settings,
                diag_sink=self._diag_sink,
                event_sink=on_event,
                cancel=self.cancel_event,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.state.error = f"{type(exc).__name__}: {exc}"
                self.state.finished = True
            return

        with self._lock:
            self.state.events = out.events
            self.state.outcome = out
            self.state.finished = True
            if out.reason == "cancelled":
                self.state.cancelled = True
                self.state.status_line = "Остановлено пользователем"

        time.sleep(0.01)
