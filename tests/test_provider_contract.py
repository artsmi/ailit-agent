"""Contract-тесты mock-провайдера."""

from __future__ import annotations

from ailit_base.capabilities import Capability
from ailit_base.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    ToolDefinition,
)
from agent_work.session.state import SessionState
from ailit_base.providers.mock_provider import MockProvider
from ailit_base.providers.protocol import ChatProvider
from agent_work.session.loop import SessionRunner, SessionSettings
from agent_work.session.tool_bridge import tool_definitions_from_registry
from agent_work.tool_runtime.approval import ApprovalSession
from agent_work.tool_runtime.permission import PermissionDecision, PermissionEngine
from agent_work.tool_runtime.registry import default_builtin_registry


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


def test_mock_write_file_session_roundtrip(tmp_path: object, monkeypatch: object) -> None:
    """Полный цикл: mock → write_file → файл на диске."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    p = MockProvider()
    reg = default_builtin_registry()
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="You are a test assistant."),
        ChatMessage(role=MessageRole.USER, content="создай tmp/hi.txt"),
    ]
    out = SessionRunner(
        p,
        reg,
        permission_engine=PermissionEngine(write_default=PermissionDecision.ALLOW),
    ).run(
        msgs,
        ApprovalSession(),
        SessionSettings(model="m", max_turns=6, temperature=0.0),
    )
    assert out.state is SessionState.FINISHED
    assert (tmp_path / "tmp" / "hi.txt").is_file()


def test_mock_complete_write_file_on_create_intent(tmp_path: object, monkeypatch: object) -> None:
    """Mock: запрос на создание файла → write_file с валидными аргументами."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    p = MockProvider()
    tools = tool_definitions_from_registry(default_builtin_registry())
    req = ChatRequest(
        messages=(
            ChatMessage(role=MessageRole.USER, content="привет сделай тестовый файл tools/foo.txt"),
        ),
        model="mock-model",
        tools=tools,
    )
    out = p.complete(req)
    assert out.tool_calls
    assert out.tool_calls[0].tool_name == "write_file"
    assert "tools/foo.txt" in out.tool_calls[0].arguments_json


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
