"""Проекция транскрипта чата: сводка инструментов, без TOOL."""

from __future__ import annotations

from agent_core.models import ChatMessage, MessageRole, ToolCallNormalized

from ailit.chat_transcript_view import (
    AssistantDisplayFormatter,
    ChatTranscriptProjector,
    SentenceBreakFormatter,
    format_tool_summary_markdown,
)


def test_transcript_skips_tool_messages() -> None:
    """TOOL не попадают в линии UI; сводка + финальный текст."""
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
    assert "Сводка инструментов" in texts
    assert "`echo`" in texts
    assert "done" in texts


def test_transcript_single_tool_wave_summary_only() -> None:
    """Только assistant с tool_calls — одна строка сводки."""
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


def test_tool_summary_counts_repeats() -> None:
    """Повторы инструментов отображаются как ×n."""
    s = format_tool_summary_markdown(["read_file", "list_dir", "read_file"])
    assert "×2" in s
    assert "list_dir" in s


def test_sentence_break_glued_russian() -> None:
    """Точка без пробела перед заглавной буквой → перенос."""
    fmt = SentenceBreakFormatter()
    out = fmt.format("Готово.Теперь дальше.")
    assert "\n\n" in out
    assert "Теперь" in out


def test_sentence_break_colon_then_capital() -> None:
    """Двоеточие сразу перед «Теперь» (типичный вывод моделей)."""
    fmt = SentenceBreakFormatter()
    raw = "описание репозитория:Теперь посмотрим на QUICK_START.md"
    out = fmt.format(raw)
    assert ":\n\nТ" in out or ":\n\n" in out


def test_assistant_display_trailing_colon_to_ellipsis() -> None:
    """Хвостовое «:» в конце ответа заменяется на «…»."""
    fmt = AssistantDisplayFormatter()
    out = fmt.format("Теперь создам скрипт:", aggressive_tail=False)
    assert out.rstrip().endswith("…")
    assert not out.rstrip().endswith(":")


def test_sentence_break_colon_space_capital() -> None:
    """«: Теперь» с пробелом."""
    fmt = SentenceBreakFormatter()
    out = fmt.format("информации: Теперь смотрим")
    assert "\n\n" in out
    assert "Теперь" in out
