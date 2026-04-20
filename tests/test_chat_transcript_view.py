"""Проекция транскрипта чата: без TOOL, компактные шаги."""

from __future__ import annotations

from agent_core.models import ChatMessage, MessageRole, ToolCallNormalized

from ailit.chat_transcript_view import ChatTranscriptProjector


def test_transcript_skips_tool_messages() -> None:
    """TOOL не попадают в линии UI."""
    tc = ToolCallNormalized(
        call_id="c1",
        tool_name="echo",
        arguments_json='{"x": 1}',
        stream_index=0,
        provider_name="p",
    )
    msgs = [
        ChatMessage(role=MessageRole.USER, content="hi"),
        ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=(tc,),
        ),
        ChatMessage(
            role=MessageRole.TOOL,
            content='{"huge": true}',
            tool_call_id="c1",
        ),
        ChatMessage(role=MessageRole.ASSISTANT, content="done"),
    ]
    lines = ChatTranscriptProjector().project(msgs)
    roles = [ln.role for ln in lines]
    assert MessageRole.TOOL not in roles
    texts = "\n".join(ln.markdown for ln in lines)
    assert "huge" not in texts
    assert "echo" in texts
    assert "done" in texts


def test_transcript_tool_call_compact_without_json_args() -> None:
    """Шаг показывает имя инструмента, не тело arguments_json."""
    tc = ToolCallNormalized(
        call_id="c2",
        tool_name="read_file",
        arguments_json='{"path": "secret.txt"}',
        stream_index=0,
        provider_name="p",
    )
    lines = ChatTranscriptProjector().project(
        [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=(tc,),
            ),
        ],
    )
    assert len(lines) == 1
    assert "read_file" in lines[0].markdown
    assert "secret" not in lines[0].markdown
