"""Сборка тела запроса OpenAI chat completions из внутреннего ChatRequest."""

from __future__ import annotations

from typing import Any

from agent_core.models import ChatMessage, ChatRequest, MessageRole, ToolDefinition


def _message_to_openai_dict(message: ChatMessage) -> dict[str, Any]:
    """Преобразовать одно сообщение в dict OpenAI API."""
    out: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.name:
        out["name"] = message.name
    if message.tool_call_id:
        out["tool_call_id"] = message.tool_call_id
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


def build_openai_chat_completion_body(request: ChatRequest) -> dict[str, Any]:
    """Построить JSON-тело для POST /v1/chat/completions."""
    body: dict[str, Any] = {
        "model": request.model,
        "messages": [_message_to_openai_dict(m) for m in request.messages],
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
    return body
