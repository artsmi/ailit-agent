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

from ailit.bash_chat_store import (
    append_execution,
    append_output_delta,
    mark_finished,
    upsert_running_call,
)


@dataclass(slots=True)
class ChatStopWorkerState:
    """Разделяемое состояние для UI-потока."""

    started: bool = False
    finished: bool = False
    stop_requested: bool = False
    cancelled: bool = False
    error: str | None = None
    assistant_text: str = ""
    status_line: str = ""
    events: tuple[dict[str, Any], ...] = ()
    outcome: SessionOutcome | None = None
    bash_executions: list[dict[str, Any]] = field(default_factory=list)
    file_change_lines: list[str] = field(default_factory=list)
    shell_store: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)


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
        with self._lock:
            self.state.stop_requested = True
        self.cancel_event.set()

    def _run(self) -> None:
        live: list[str] = []
        file_changes: list[str] = []
        bash_execs: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        shell_idx_by_call_id: dict[str, int] = {}

        def _append_thought(text: str) -> None:
            if not text:
                return
            if timeline and timeline[-1].get("kind") == "thought":
                timeline[-1]["text"] = str(timeline[-1].get("text", "")) + text
            else:
                timeline.append({"kind": "thought", "text": text})

        def _ensure_shell_block(
            *,
            call_id: str,
            tool_name: str,
            command: str,
        ) -> None:
            if call_id in shell_idx_by_call_id:
                i = shell_idx_by_call_id[call_id]
                if (
                    0 <= i < len(timeline)
                    and timeline[i].get("kind") == "shell"
                ):
                    timeline[i]["tool_name"] = tool_name
                    timeline[i]["command"] = command
                    return
            timeline.append(
                {
                    "kind": "shell",
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "command": command,
                    "status": "running",
                    "combined_output": "",
                },
            )
            shell_idx_by_call_id[call_id] = len(timeline) - 1

        def on_event(ev: object) -> None:
            et = getattr(ev, "type", "")
            payload = getattr(ev, "payload", {})
            if et == "assistant.delta" and isinstance(payload, dict):
                txt = payload.get("text")
                if isinstance(txt, str) and txt:
                    live.append(txt)
                    with self._lock:
                        self.state.assistant_text = "".join(live)
                        _append_thought(txt)
                        self.state.timeline = list(timeline)
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
                    append_execution(self.state.shell_store, payload)
                    cid = str(payload.get("call_id") or "")
                    if cid and cid in shell_idx_by_call_id:
                        i = shell_idx_by_call_id[cid]
                        if (
                            0 <= i < len(timeline)
                            and timeline[i].get("kind") == "shell"
                        ):
                            timeline[i]["status"] = (
                                "ok" if payload.get("ok") else "error"
                            )
                            timeline[i]["combined_output"] = str(
                                payload.get("combined_output") or "",
                            )
                            self.state.timeline = list(timeline)
                return
            if et == "bash.output_delta" and isinstance(payload, dict):
                cid = payload.get("call_id")
                ch = payload.get("chunk")
                if isinstance(cid, str) and isinstance(ch, str):
                    with self._lock:
                        append_output_delta(
                            self.state.shell_store,
                            call_id=cid,
                            chunk=ch,
                        )
                        if cid in shell_idx_by_call_id:
                            i = shell_idx_by_call_id[cid]
                            if (
                                0 <= i < len(timeline)
                                and timeline[i].get("kind") == "shell"
                            ):
                                prev = str(
                                    timeline[i].get(
                                        "combined_output",
                                        "",
                                    )
                                    or "",
                                )
                                timeline[i]["combined_output"] = prev + ch
                                self.state.timeline = list(timeline)
                return
            if et == "bash.finished" and isinstance(payload, dict):
                cid = payload.get("call_id")
                ok = payload.get("ok")
                err = payload.get("error")
                if isinstance(cid, str):
                    with self._lock:
                        mark_finished(
                            self.state.shell_store,
                            call_id=cid,
                            ok=bool(ok is True),
                            error=str(err) if err else None,
                        )
                        if cid in shell_idx_by_call_id:
                            i = shell_idx_by_call_id[cid]
                            if (
                                0 <= i < len(timeline)
                                and timeline[i].get("kind") == "shell"
                            ):
                                timeline[i]["status"] = (
                                    "ok" if ok is True else "error"
                                )
                                if err:
                                    timeline[i]["error"] = str(err)
                                self.state.timeline = list(timeline)
                return
            if et == "tool.call_started" and isinstance(payload, dict):
                tn = payload.get("tool")
                cid = payload.get("call_id")
                args_json = payload.get("arguments_json")
                if isinstance(tn, str) and tn.strip():
                    with self._lock:
                        name = tn.strip()
                        self.state.status_line = f"Шаг: {name}"
                if (
                    isinstance(tn, str)
                    and tn in ("run_shell", "run_shell_session", "shell_reset")
                    and isinstance(cid, str)
                    and isinstance(args_json, str)
                ):
                    cmd = ""
                    try:
                        import json as _json

                        raw = _json.loads(args_json)
                        if isinstance(raw, dict):
                            cmd = str(raw.get("command", "") or "").strip()
                    except Exception:
                        cmd = ""
                    with self._lock:
                        upsert_running_call(
                            self.state.shell_store,
                            call_id=cid,
                            command=cmd,
                            tool_name=tn,
                        )
                        _ensure_shell_block(
                            call_id=cid,
                            tool_name=tn,
                            command=cmd,
                        )
                        self.state.timeline = list(timeline)
                return
            if et == "tool.call_finished" and isinstance(payload, dict):
                tn = payload.get("tool")
                cid = payload.get("call_id")
                ok = payload.get("ok")
                err = payload.get("error")
                if (
                    isinstance(tn, str)
                    and tn in ("run_shell", "run_shell_session", "shell_reset")
                    and isinstance(cid, str)
                ):
                    with self._lock:
                        mark_finished(
                            self.state.shell_store,
                            call_id=cid,
                            ok=bool(ok is True),
                            error=str(err) if err else None,
                        )
                        if cid in shell_idx_by_call_id:
                            i = shell_idx_by_call_id[cid]
                            if (
                                0 <= i < len(timeline)
                                and timeline[i].get("kind") == "shell"
                            ):
                                timeline[i]["status"] = (
                                    "ok" if ok is True else "error"
                                )
                                if err:
                                    timeline[i]["error"] = str(err)
                                self.state.timeline = list(timeline)
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
