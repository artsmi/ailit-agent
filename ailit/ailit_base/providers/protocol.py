"""Протокол провайдера: единая точка для session loop без vendor-логики.

Опциональный метод на реализации: `build_stream_incremental()` — см.
`agent_core.normalization.stream_to_incremental` (Kimi и др.).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from ailit_base.capabilities import Capability
from ailit_base.models import ChatRequest, NormalizedChatResponse, StreamEvent


@runtime_checkable
class ChatProvider(Protocol):
    """Провайдер чата: completion и stream."""

    @property
    def provider_id(self) -> str:
        """Стабильный идентификатор для capability matrix и телеметрии."""
        ...

    def capabilities(self) -> frozenset[Capability]:
        """Декларируемые capability (из матрицы)."""
        ...

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        """Небуферизованный chat completion."""
        ...

    def stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        """Поток событий; завершается StreamDone."""
        ...
