"""Contract-тесты mock-провайдера."""

from __future__ import annotations

from agent_core.capabilities import Capability
from agent_core.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    ToolDefinition,
)
from agent_core.providers.mock_provider import MockProvider
from agent_core.providers.protocol import ChatProvider


def _typing_protocol_holds(provider: ChatProvider) -> None:
    assert hasattr(provider, "provider_id")
    assert hasattr(provider, "capabilities")
    assert hasattr(provider, "complete")
    assert hasattr(provider, "stream")


def test_mock_provider_satisfies_protocol() -> None:
    """MockProvider структурно удовлетворяет ChatProvider."""
    p = MockProvider()
    _typing_protocol_holds(p)
    assert Capability.CHAT in p.capabilities()


def test_mock_complete_text_shape() -> None:
    """Без tools — текст и usage."""
    p = MockProvider()
    req = ChatRequest(
        messages=(ChatMessage(role=MessageRole.USER, content="hi"),),
        model="mock-model",
    )
    out = p.complete(req)
    assert out.text_parts
    assert out.finish_reason is FinishReason.STOP
    assert not out.usage.usage_missing


def test_mock_complete_with_tools_shape() -> None:
    """С tools — нормализованный tool call."""
    p = MockProvider()
    tools = (
        ToolDefinition(
            name="demo_tool",
            description="demo",
            parameters={"type": "object", "properties": {}},
        ),
    )
    req = ChatRequest(
        messages=(ChatMessage(role=MessageRole.USER, content="call tool"),),
        model="mock-model",
        tools=tools,
    )
    out = p.complete(req)
    assert out.tool_calls
    assert out.tool_calls[0].tool_name == "demo_tool"
    assert out.finish_reason is FinishReason.TOOL_CALLS
