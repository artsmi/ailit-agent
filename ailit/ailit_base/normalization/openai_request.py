"""Сборка тела запроса OpenAI chat completions из внутреннего ChatRequest."""

from __future__ import annotations

from typing import Any

from ailit_base.models import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolDefinition,
)


def _sanitize_tool_messages(
    messages: tuple[ChatMessage, ...],
) -> list[ChatMessage]:
    """Drop orphan TOOL messages without preceding assistant tool_calls.

    OpenAI-compat APIs require TOOL messages to be responses to tool_calls.
    Compaction/prune may drop the assistant tool_calls message while leaving
    TOOL messages behind; such orphans must not be sent.
    """
    seen_call_ids: set[str] = set()
    out: list[ChatMessage] = []
    for m in messages:
        if m.role is MessageRole.ASSISTANT and m.tool_calls:
            for tc in m.tool_calls:
                if tc.call_id:
                    seen_call_ids.add(str(tc.call_id))
            out.append(m)
            continue
        if m.role is MessageRole.TOOL and m.tool_call_id:
            if str(m.tool_call_id) in seen_call_ids:
                out.append(m)
            continue
        out.append(m)
    return out


def _message_to_openai_dict(message: ChatMessage) -> dict[str, Any]:
    """Преобразовать одно сообщение в dict OpenAI API."""
    out: dict[str, Any] = {"role": message.role.value}
    if message.tool_calls and not message.content:
        out["content"] = None
    else:
        out["content"] = message.content
    if message.name:
        out["name"] = message.name
    if message.tool_call_id:
        out["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.call_id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": tc.arguments_json,
                },
            }
            for tc in message.tool_calls
        ]
    return out


def _tool_to_openai_dict(tool: ToolDefinition) -> dict[str, Any]:
    """Преобразовать ToolDefinition в формат tools[]."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _response_format_from_extra(extra: Any) -> dict[str, Any] | None:
    """Return OpenAI-compatible response_format from request extra."""
    if not isinstance(extra, dict):
        return None
    direct = extra.get("response_format")
    if isinstance(direct, dict):
        fmt = str(direct.get("type", "") or "").strip()
        return dict(direct) if fmt else None
    memory_llm = extra.get("memory_llm")
    if not isinstance(memory_llm, dict):
        return None
    nested = memory_llm.get("openai_response_format")
    if isinstance(nested, dict):
        fmt = str(nested.get("type", "") or "").strip()
        return dict(nested) if fmt else None
    mode = str(memory_llm.get("response_format", "") or "").strip()
    if mode in ("json_schema", "json_object"):
        return {"type": "json_object"}
    return None


def build_openai_chat_completion_body(request: ChatRequest) -> dict[str, Any]:
    """Построить JSON-тело для POST /v1/chat/completions."""
    sanitized = _sanitize_tool_messages(tuple(request.messages))
    body: dict[str, Any] = {
        "model": request.model,
        "messages": [_message_to_openai_dict(m) for m in sanitized],
        "temperature": request.temperature,
        "stream": request.stream,
    }
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.tools:
        body["tools"] = [_tool_to_openai_dict(t) for t in request.tools]
    if request.tool_choice is not None:
        body["tool_choice"] = request.tool_choice.mode
    if request.strict_json_schema and request.tools:
        for item in body["tools"]:
            fn = item.get("function")
            if isinstance(fn, dict):
                fn["strict"] = True
    response_format = _response_format_from_extra(request.extra)
    if response_format is not None:
        body["response_format"] = response_format
    return body
