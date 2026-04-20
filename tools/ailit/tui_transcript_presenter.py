"""Презентация событий session loop для TUI.

Компактные шаги (dim), без сырых payload инструментов.
"""

from __future__ import annotations

from typing import Any, Mapping

from rich.markup import escape
from rich.text import Text


class ModelRequestEventLine:
    """Строка события ``model.request``."""

    def build(self, payload: Mapping[str, Any]) -> Text:
        """Строка «запрос к модели» (аналог индикатора загрузки)."""
        n_tools = payload.get("tools_count")
        tools_s = str(n_tools) if n_tools is not None else "?"
        return Text.assemble(
            ("· ", "dim"),
            ("модель", "dim italic"),
            (f" (tools={tools_s})…", "dim"),
        )


class ToolCallStartedEventLine:
    """Строка ``tool.call_started``."""

    def build(self, payload: Mapping[str, Any]) -> Text:
        """Начало вызова инструмента."""
        name = payload.get("tool")
        tool_s = escape(str(name)) if isinstance(name, str) else "?"
        cid = payload.get("call_id")
        tail = f" `{escape(str(cid))}`" if isinstance(cid, str) and cid else ""
        return Text.assemble(
            ("  → ", "dim"),
            (tool_s, "cyan"),
            (tail, "dim"),
            (" …", "dim"),
        )


class ToolCallFinishedEventLine:
    """Строка ``tool.call_finished``."""

    def build(self, payload: Mapping[str, Any]) -> Text:
        """Завершение вызова инструмента."""
        name = payload.get("tool")
        tool_s = escape(str(name)) if isinstance(name, str) else "?"
        ok = payload.get("ok")
        ok_s = "ok" if ok is True else ("err" if ok is False else "?")
        style = "green" if ok is True else ("red" if ok is False else "dim")
        return Text.assemble(
            ("  ← ", "dim"),
            (tool_s, "cyan"),
            (f" ({ok_s})", style),
        )


class TuiTranscriptEventPresenter:
    """Фасад: одна точка для ``AilitTuiApp.on_event``."""

    def __init__(self) -> None:
        """Собрать вложенные форматтеры строк."""
        self._model = ModelRequestEventLine()
        self._tool_start = ToolCallStartedEventLine()
        self._tool_end = ToolCallFinishedEventLine()

    def model_request_line(self, payload: Mapping[str, Any]) -> Text:
        """Делегат для ``model.request``."""
        return self._model.build(payload)

    def tool_started_line(self, payload: Mapping[str, Any]) -> Text:
        """Делегат для ``tool.call_started``."""
        return self._tool_start.build(payload)

    def tool_finished_line(self, payload: Mapping[str, Any]) -> Text:
        """Делегат для ``tool.call_finished``."""
        return self._tool_end.build(payload)
