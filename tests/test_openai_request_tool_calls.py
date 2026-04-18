"""Сообщение assistant с tool_calls в теле OpenAI."""

from __future__ import annotations

from agent_core.models import ChatMessage, MessageRole, ToolCallNormalized
from agent_core.normalization.openai_request import build_openai_chat_completion_body
from agent_core.models import ChatRequest


def test_assistant_tool_calls_serialized() -> None:
    """OpenAI dict содержит tool_calls и null content."""
    tc = ToolCallNormalized("c1", "echo", "{}", 0, "mock")
    msg = ChatMessage(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=(tc,),
    )
    body = build_openai_chat_completion_body(
        ChatRequest(messages=(msg,), model="m"),
    )
    m0 = body["messages"][0]
    assert m0["role"] == "assistant"
    assert m0.get("content") is None
    assert "tool_calls" in m0
