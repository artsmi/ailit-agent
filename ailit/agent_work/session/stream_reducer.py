"""Централизованный сбор streaming событий в NormalizedChatResponse."""

from __future__ import annotations

from collections.abc import Iterator

from ailit_base.models import NormalizedChatResponse, StreamDone, StreamEvent


class StreamReducer:
    """Свести поток StreamEvent к финальному NormalizedChatResponse."""

    @staticmethod
    def consume(events: Iterator[StreamEvent]) -> NormalizedChatResponse:
        """Прочитать поток до StreamDone или бросить ValueError."""
        last: NormalizedChatResponse | None = None
        for event in events:
            if isinstance(event, StreamDone):
                last = event.response
        if last is None:
            msg = "stream ended without StreamDone"
            raise ValueError(msg)
        return last
