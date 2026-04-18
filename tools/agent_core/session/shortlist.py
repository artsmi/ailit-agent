"""Shortlist по ключевым словам (MVP без retrieval-слоя)."""

from __future__ import annotations

from agent_core.models import ChatMessage, MessageRole


def apply_keyword_shortlist(
    messages: Sequence[ChatMessage],
    keywords: frozenset[str],
) -> list[ChatMessage]:
    """Оставить system, последнее user-сообщение и сообщения с любым keyword."""
    if not keywords:
        return list(messages)
    keep: set[int] = set()
    for i, m in enumerate(messages):
        if m.role is MessageRole.SYSTEM:
            keep.add(i)
        lower = m.content.lower()
        for kw in keywords:
            if kw.lower() in lower:
                keep.add(i)
                break
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role is MessageRole.USER:
            keep.add(i)
            break
    return [messages[i] for i in sorted(keep)]
