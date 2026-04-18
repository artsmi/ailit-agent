"""Внутренние контракты запросов и нормализованных ответов."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class MessageRole(str, Enum):
    """Роль сообщения в диалоге."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(str, Enum):
    """Нормализованная причина завершения генерации."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Одно сообщение в формате runtime."""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Описание инструмента (JSON Schema в OpenAI-стиле)."""

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolChoice:
    """Выбор режима tool calling."""

    mode: str  # "auto" | "none" | "required" | ...


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Политика повторов HTTP."""

    max_attempts: int = 3
    backoff_base_seconds: float = 0.5


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Таймауты HTTP."""

    connect_seconds: float = 10.0
    read_seconds: float = 120.0
    write_seconds: float = 30.0
    pool_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """Единый внутренний запрос к провайдеру."""

    messages: Sequence[ChatMessage]
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: Sequence[ToolDefinition] = ()
    tool_choice: ToolChoice | None = None
    stream: bool = False
    strict_json_schema: bool = False
    timeout: TimeoutPolicy = field(default_factory=TimeoutPolicy)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    """Нормализованная телеметрия usage."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    usage_missing: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallNormalized:
    """Единый формат tool call после нормализации."""

    call_id: str
    tool_name: str
    arguments_json: str
    stream_index: int
    provider_name: str
    is_complete: bool = True


@dataclass(frozen=True, slots=True)
class NormalizedChatResponse:
    """Нормализованный ответ провайдера."""

    text_parts: tuple[str, ...]
    tool_calls: tuple[ToolCallNormalized, ...]
    finish_reason: FinishReason
    usage: NormalizedUsage
    provider_metadata: Mapping[str, Any]
    raw_debug_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class StreamTextDelta:
    """Фрагмент текста в потоке."""

    text: str


@dataclass(frozen=True, slots=True)
class StreamToolDelta:
    """Накопление аргументов tool call в потоке."""

    index: int
    call_id: str | None
    tool_name: str | None
    arguments_fragment: str


@dataclass(frozen=True, slots=True)
class StreamDone:
    """Завершение потока с итоговой нормализацией."""

    response: NormalizedChatResponse


StreamEvent = StreamTextDelta | StreamToolDelta | StreamDone
