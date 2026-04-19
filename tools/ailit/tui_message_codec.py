"""Сериализация ``ChatMessage`` для сохранения TUI-сессий (Q.3)."""

from __future__ import annotations

from typing import Any

from agent_core.models import ChatMessage, MessageRole


def messages_to_jsonable(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Список сообщений → JSON-совместимые dict (без tool_calls)."""
    rows: list[dict[str, Any]] = []
    for m in messages:
        row: dict[str, Any] = {
            "role": m.role.value,
            "content": m.content,
        }
        if m.tool_call_id:
            row["tool_call_id"] = m.tool_call_id
        if m.name:
            row["name"] = m.name
        rows.append(row)
    return rows


def messages_from_jsonable(rows: list[dict[str, Any]]) -> list[ChatMessage]:
    """Восстановить сообщения из сохранённого JSON."""
    out: list[ChatMessage] = []
    for d in rows:
        role = MessageRole(str(d.get("role", "user")))
        content = str(d.get("content", ""))
        tid = d.get("tool_call_id")
        name = d.get("name")
        out.append(
            ChatMessage(
                role=role,
                content=content,
                name=str(name) if name is not None else None,
                tool_call_id=str(tid) if tid is not None else None,
            ),
        )
    return out
