"""Контракт событий session loop для UI (DP-3.1).

Цель: UI (Streamlit/Textual/CLI) подписывается на единый поток событий, не
зависящий от деталей провайдера. События должны быть достаточно узкими, чтобы:
- показывать дельты ассистента во время streaming;
- показывать запуск/результаты инструментов;
- показывать usage и ошибки.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """Базовый тип события."""

    type: str
    payload: Mapping[str, Any]


SessionEventSink = Callable[[SessionEvent], None]


class SupportsSessionEvents(Protocol):
    """Опциональная подписка на события."""

    def on_session_event(self, event: SessionEvent) -> None:
        """Получить событие session loop."""
