"""Compaction и shortlist."""

from __future__ import annotations

from ailit_base.models import ChatMessage, MessageRole
from agent_work.session.compaction import compact_messages
from agent_work.session.shortlist import apply_keyword_shortlist


def test_compaction_truncates_long_tool_output() -> None:
    """TOOL сообщение усечено."""
    long = "a" * 50
    messages = [
        ChatMessage(role=MessageRole.USER, content="u"),
        ChatMessage(role=MessageRole.TOOL, content=long, tool_call_id="c1"),
    ]
    out = compact_messages(messages, tail_max=10, max_tool_chars=20)
    tool_msg = next(m for m in out if m.role is MessageRole.TOOL)
    assert len(tool_msg.content) < len(long)
    assert "truncated" in tool_msg.content


def test_shortlist_keeps_keyword_and_last_user() -> None:
    """Shortlist оставляет system, keyword и последний user."""
    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content="sys"),
        ChatMessage(role=MessageRole.USER, content="alpha secret gamma"),
        ChatMessage(role=MessageRole.USER, content="last question"),
    ]
    out = apply_keyword_shortlist(messages, frozenset({"secret"}))
    texts = [m.content for m in out]
    assert "sys" in texts
    assert any("secret" in t for t in texts)
    assert texts[-1] == "last question"
