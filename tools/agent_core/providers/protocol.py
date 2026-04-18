"""Протокол провайдера: единая точка для session loop без vendor-логики."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from agent_core.capabilities import Capability
from agent_core.models import ChatRequest, NormalizedChatResponse, StreamEvent


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
