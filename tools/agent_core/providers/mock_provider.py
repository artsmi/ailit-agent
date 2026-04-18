"""Детерминированный mock-провайдер для contract-тестов."""

from __future__ import annotations

from collections.abc import Iterator

from agent_core.capabilities import Capability, capability_set_for
from agent_core.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
    StreamDone,
    StreamEvent,
    StreamTextDelta,
    ToolCallNormalized,
)


class MockProvider:
    """Провайдер без сети: предсказуемые ответы."""

    @property
    def provider_id(self) -> str:
        return "mock"

    def capabilities(self) -> frozenset[Capability]:
        return capability_set_for(self.provider_id)

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        """Вернуть фиксированный ответ; учитывать инструменты для smoke сценариев."""
        if request.tools:
            tc = ToolCallNormalized(
                call_id="mock_call_1",
                tool_name=request.tools[0].name,
                arguments_json="{}",
                stream_index=0,
                provider_name=self.provider_id,
                is_complete=True,
            )
            return NormalizedChatResponse(
                text_parts=(),
                tool_calls=(tc,),
                finish_reason=FinishReason.TOOL_CALLS,
                usage=NormalizedUsage(
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                    usage_missing=False,
                ),
                provider_metadata={"provider_id": self.provider_id, "mock": True},
                raw_debug_payload=None,
            )
        return NormalizedChatResponse(
            text_parts=("mock-ok",),
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            usage=NormalizedUsage(
                input_tokens=3,
                output_tokens=2,
                total_tokens=5,
                usage_missing=False,
            ),
            provider_metadata={"provider_id": self.provider_id, "mock": True},
            raw_debug_payload=None,
        )

    def stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        """Упростить stream до текстовых дельт и финального StreamDone."""
        yield StreamTextDelta(text="mock")
        yield StreamTextDelta(text="-ok")
        final = self.complete(
            ChatRequest(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=(),
                tool_choice=None,
                stream=False,
                strict_json_schema=request.strict_json_schema,
                timeout=request.timeout,
                retry=request.retry,
                extra=request.extra,
            )
        )
        yield StreamDone(response=final)
