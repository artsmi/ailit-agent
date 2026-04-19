"""Нормализация ответа OpenAI-совместимого chat completions."""

from __future__ import annotations

import json
from typing import Any, Mapping

from agent_core.models import (
    FinishReason,
    NormalizedChatResponse,
    ToolCallNormalized,
)
from agent_core.normalization.content_sanitize import AssistantContentSanitizer
from agent_core.normalization.tool_fallback import try_parse_tool_calls_from_text
from agent_core.normalization.usage_fields import normalize_usage_payload


def _map_finish_reason(raw: str | None) -> FinishReason:
    if raw is None:
        return FinishReason.UNKNOWN
    mapping = {
        "stop": FinishReason.STOP,
        "length": FinishReason.LENGTH,
        "tool_calls": FinishReason.TOOL_CALLS,
        "content_filter": FinishReason.CONTENT_FILTER,
    }
    return mapping.get(raw, FinishReason.UNKNOWN)


def normalize_chat_completion(
    payload: Mapping[str, Any],
    *,
    provider_id: str,
    enable_parser_fallback: bool = True,
) -> NormalizedChatResponse:
    """Разобрать JSON ответ chat completion в NormalizedChatResponse."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("choices must be a non-empty list")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("choice must be object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("message must be object")

    content = message.get("content")
    text_parts: list[str] = []
    if isinstance(content, str) and content.strip():
        text_parts.append(content)

    tool_calls: list[ToolCallNormalized] = []
    raw_tool_calls = message.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        for idx, tc in enumerate(raw_tool_calls):
            if not isinstance(tc, dict):
                continue
            call_id = str(tc.get("id") or f"call_{idx}")
            fn = tc.get("function")
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name") or "")
            args = fn.get("arguments")
            args_str = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            tool_calls.append(
                ToolCallNormalized(
                    call_id=call_id,
                    tool_name=name,
                    arguments_json=args_str,
                    stream_index=idx,
                    provider_name=provider_id,
                    is_complete=True,
                )
            )

    if not tool_calls and enable_parser_fallback and text_parts:
        fallback = try_parse_tool_calls_from_text(text_parts[0], provider_id=provider_id)
        tool_calls.extend(fallback)

    has_tools = bool(tool_calls)
    text_parts = [
        AssistantContentSanitizer.sanitize(part, aggressive_trailing=has_tools)
        for part in text_parts
    ]
    text_parts = [part for part in text_parts if part]

    finish_raw = first.get("finish_reason")
    finish_reason = _map_finish_reason(finish_raw if isinstance(finish_raw, str) else None)

    usage_obj = payload.get("usage")
    usage_mapping: Mapping[str, Any] | None = (
        usage_obj if isinstance(usage_obj, dict) else None
    )
    usage = normalize_usage_payload(usage_mapping)

    meta: dict[str, Any] = {
        "provider_id": provider_id,
        "model": payload.get("model"),
        "id": payload.get("id"),
    }
    if usage.usage_unknown:
        meta["usage_unknown_tail"] = dict(usage.usage_unknown)
    return NormalizedChatResponse(
        text_parts=tuple(text_parts),
        tool_calls=tuple(tool_calls),
        finish_reason=finish_reason,
        usage=usage,
        provider_metadata=meta,
        raw_debug_payload=dict(payload) if payload else None,
    )
