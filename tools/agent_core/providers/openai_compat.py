"""Общая реализация для OpenAI-совместимых провайдеров (DeepSeek, Kimi/Moonshot)."""

from __future__ import annotations

from collections.abc import Iterator

from agent_core.capabilities import Capability, capability_set_for
from agent_core.models import ChatRequest, NormalizedChatResponse, StreamEvent
from agent_core.normalization.openai_normalize import normalize_chat_completion
from agent_core.normalization.openai_request import build_openai_chat_completion_body
from agent_core.normalization.stream_assembler import iter_stream_events_from_sse_lines
from agent_core.transport.httpx_transport import HttpxJsonTransport
from agent_core.transport.retry_runner import run_with_retry


class OpenAICompatProvider:
    """HTTP вызовы chat completions + нормализация ответа."""

    def __init__(
        self,
        *,
        provider_id: str,
        api_root: str,
        api_key: str,
        transport: HttpxJsonTransport | None = None,
    ) -> None:
        """Инициализировать адаптер с корнем API (`.../v1`)."""
        self._provider_id = provider_id
        self._api_root = api_root.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    def _transport_for(self, request: ChatRequest) -> HttpxJsonTransport:
        """Вернуть транспорт с таймаутами из запроса или инжектированный."""
        if self._transport is not None:
            return self._transport
        return HttpxJsonTransport(timeout_policy=request.timeout)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def capabilities(self) -> frozenset[Capability]:
        return capability_set_for(self._provider_id)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _chat_completions_url(self) -> str:
        return f"{self._api_root}/chat/completions"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        """Выполнить non-stream запрос и нормализовать ответ."""
        body = build_openai_chat_completion_body(
            ChatRequest(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
                tool_choice=request.tool_choice,
                stream=False,
                strict_json_schema=request.strict_json_schema,
                timeout=request.timeout,
                retry=request.retry,
                extra=request.extra,
            )
        )

        tx = self._transport_for(request)

        def call() -> dict[str, object]:
            return tx.post_json(
                self._chat_completions_url(),
                headers=self._headers(),
                body=body,
            )

        raw = run_with_retry(call, request.retry)
        return normalize_chat_completion(
            raw,
            provider_id=self._provider_id,
            enable_parser_fallback=True,
        )

    def stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        """Streaming SSE → StreamEvent."""
        body = build_openai_chat_completion_body(
            ChatRequest(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
                tool_choice=request.tool_choice,
                stream=True,
                strict_json_schema=request.strict_json_schema,
                timeout=request.timeout,
                retry=request.retry,
                extra=request.extra,
            )
        )

        tx = self._transport_for(request)
        lines = tx.post_sse_lines(
            self._chat_completions_url(),
            headers=self._headers(),
            body=body,
        )
        yield from iter_stream_events_from_sse_lines(lines, provider_id=self._provider_id)
