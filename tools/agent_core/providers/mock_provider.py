"""Детерминированный mock-провайдер для contract-тестов."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence

from agent_core.capabilities import Capability, capability_set_for
from agent_core.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
    StreamDone,
    StreamEvent,
    StreamTextDelta,
    ToolCallNormalized,
)


_PERM_CLASSIFIER_MARKER = "[AILIT_PERM_MODE_CLASSIFIER_V1]"


def _last_non_system(messages: Sequence[ChatMessage]) -> ChatMessage | None:
    for m in reversed(messages):
        if m.role is not MessageRole.SYSTEM:
            return m
    return None


def _perm_classifier_prompt(messages: Sequence[ChatMessage]) -> bool:
    for m in messages:
        if m.role is not MessageRole.SYSTEM:
            continue
        if _PERM_CLASSIFIER_MARKER in (m.content or ""):
            return True
    return False


def _mock_perm_classifier_output(last: ChatMessage | None) -> str:
    text = (last.content if last and last.role is MessageRole.USER else "") or ""
    low = text.lower()
    if "not_sure" in low or "не уверен" in low:
        mode = "not_sure"
    elif ("точк" in low and "вход" in low) or "entry point" in low:
        mode = "read"
    elif "docs/" in low or "plan.md" in low:
        mode = "read_plan"
    else:
        mode = "explore"
    return json.dumps(
        {"mode": mode, "confidence": 0.9, "reason": "mock heuristic"},
        ensure_ascii=False,
    )


def _tool_names(request: ChatRequest) -> frozenset[str]:
    if not request.tools:
        return frozenset()
    return frozenset(t.name for t in request.tools)


def _wants_create_file(text: str) -> bool:
    low = text.lower()
    keys = (
        "write_file",
        "создай файл",
        "тестовый файл",
        "test file",
        "создать файл",
    )
    if any(k in low for k in keys):
        return True
    if "создай" in low and "файл" in low:
        return True
    if "создай" in low and any(ext in low for ext in (".txt", ".py", ".md", ".yaml", ".yml")):
        return True
    if "сделай" in low and ("файл" in low or "тест" in low):
        return True
    if "create" in low and "file" in low:
        return True
    return False


def _rel_path_from_user(text: str) -> str | None:
    m = re.search(r"([\w./\\-]+\.(?:py|txt|md|yaml|yml))\b", text, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).replace("\\", "/")


class MockProvider:
    """Провайдер без сети: предсказуемые ответы."""

    @property
    def provider_id(self) -> str:
        return "mock"

    def capabilities(self) -> frozenset[Capability]:
        return capability_set_for(self.provider_id)

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        """Вернуть фиксированный ответ; учитывать инструменты для smoke сценариев."""
        last = _last_non_system(request.messages)
        if last is not None and last.role is MessageRole.TOOL:
            return NormalizedChatResponse(
                text_parts=("Готово (mock): результат инструмента учтён.",),
                tool_calls=(),
                finish_reason=FinishReason.STOP,
                usage=NormalizedUsage(
                    input_tokens=10,
                    output_tokens=6,
                    total_tokens=16,
                    usage_missing=False,
                ),
                provider_metadata={"provider_id": self.provider_id, "mock": True},
                raw_debug_payload=None,
            )

        names = _tool_names(request)
        if (
            last is not None
            and last.role is MessageRole.USER
            and request.tools
            and "write_file" in names
            and _wants_create_file(last.content)
        ):
            path = _rel_path_from_user(last.content) or "tmp/ailit_chat_test.txt"
            body = "# test file (mock)\n"
            args = json.dumps({"path": path, "content": body}, ensure_ascii=False)
            tc = ToolCallNormalized(
                call_id="mock_call_write",
                tool_name="write_file",
                arguments_json=args,
                stream_index=0,
                provider_name=self.provider_id,
                is_complete=True,
            )
            return NormalizedChatResponse(
                text_parts=(),
                tool_calls=(tc,),
                finish_reason=FinishReason.TOOL_CALLS,
                usage=NormalizedUsage(
                    input_tokens=12,
                    output_tokens=8,
                    total_tokens=20,
                    usage_missing=False,
                ),
                provider_metadata={"provider_id": self.provider_id, "mock": True},
                raw_debug_payload=None,
            )

        if not request.tools and _perm_classifier_prompt(request.messages):
            body = _mock_perm_classifier_output(last)
            return NormalizedChatResponse(
                text_parts=(body,),
                tool_calls=(),
                finish_reason=FinishReason.STOP,
                usage=NormalizedUsage(
                    input_tokens=8,
                    output_tokens=12,
                    total_tokens=20,
                    usage_missing=False,
                ),
                provider_metadata={"provider_id": self.provider_id, "mock": True},
                raw_debug_payload=None,
            )

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
                tools=request.tools,
                tool_choice=request.tool_choice,
                stream=False,
                strict_json_schema=request.strict_json_schema,
                timeout=request.timeout,
                retry=request.retry,
                extra=request.extra,
            )
        )
        yield StreamDone(response=final)
