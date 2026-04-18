"""Усечение истории и длинных tool-ответов."""

from __future__ import annotations

from agent_core.models import ChatMessage, MessageRole


def compact_messages(
    messages: list[ChatMessage],
    *,
    tail_max: int,
    max_tool_chars: int,
) -> list[ChatMessage]:
    """Оставить хвост из tail_max сообщений; усечь длинные TOOL content."""
    if tail_max <= 0:
        return []
    base = messages[-tail_max:] if len(messages) > tail_max else list(messages)
    out: list[ChatMessage] = []
    for m in base:
        if m.role is MessageRole.TOOL and len(m.content) > max_tool_chars:
            truncated = m.content[:max_tool_chars] + "...[truncated]"
            out.append(
                ChatMessage(
                    role=m.role,
                    content=truncated,
                    name=m.name,
                    tool_call_id=m.tool_call_id,
                    tool_calls=m.tool_calls,
                )
            )
        else:
            out.append(m)
    return out
