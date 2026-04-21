"""Фоновый прогон LLM для TUI: thread + доставка событий в UI-поток."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from agent_core.session.event_contract import SessionEvent
from agent_core.shell_output_preview import LineTailSelector


@dataclass(slots=True)
class TuiLlmTurnOutcome:
    """Результат одного пользовательского хода (из worker-потока)."""

    text: str
    status_line: str
    usage: dict[str, Any] | None
    turn_tools: list[str] = field(default_factory=list)
    error: BaseException | None = None


class TuiThreadUiSessionSink:
    """event_sink в worker: UI через ``App.call_from_thread``."""

    _preview_stride: int = 160

    def __init__(self, app: Any) -> None:
        """Привязать приложение и буферы."""
        self._app = app
        self.turn_tools: list[str] = []
        self._stream_parts: list[str] = []
        self._last_preview_len: int = 0
        self._bash_chunks: dict[str, list[str]] = {}

    def __call__(self, ev: SessionEvent) -> None:
        """Пробросить событие session loop в UI-поток."""
        pl = dict(ev.payload) if isinstance(ev.payload, Mapping) else {}
        et = ev.type
        if et == "model.request":
            self._app.call_from_thread(self._app._ui_session_model_request, pl)
            return
        if et == "tool.call_started":
            tn = pl.get("tool")
            if isinstance(tn, str) and tn.strip():
                self.turn_tools.append(tn.strip())
            self._app.call_from_thread(self._app._ui_session_tool_started, pl)
            return
        if et == "tool.call_finished":
            self._app.call_from_thread(self._app._ui_session_tool_finished, pl)
            return
        if et == "bash.output_delta":
            cid = str(pl.get("call_id") or "")
            ch = pl.get("chunk")
            if cid and isinstance(ch, str):
                self._bash_chunks.setdefault(cid, []).append(ch)
            return
        if et == "bash.finished":
            cid = str(pl.get("call_id") or "")
            full = "".join(self._bash_chunks.pop(cid, []))
            if full.strip():
                tail = LineTailSelector.last_lines(full, 4)
                self._app.call_from_thread(
                    self._app._ui_bash_shell_preview,
                    tail,
                )
            return
        if et != "assistant.delta":
            return
        raw = pl.get("text")
        if not isinstance(raw, str) or not raw:
            return
        self._stream_parts.append(raw)
        joined = "".join(self._stream_parts)
        if (
            len(joined) - self._last_preview_len < self._preview_stride
            and not raw.endswith("\n")
        ):
            return
        self._last_preview_len = len(joined)
        self._app.call_from_thread(
            self._app._ui_session_assistant_joined,
            joined,
        )
