"""System addendum для агентов с ролью ``teammate`` (этап L.2)."""

from __future__ import annotations

# Смысл как у TEAMMATE_SYSTEM_PROMPT_ADDENDUM в Claude Code: чат пользователя
# не доставляет сообщения другим агентам.
TEAMMATE_MAILBOX_SYSTEM_ADDENDUM: str = (
    "Teammate / multi-agent mode: Other agents do NOT see normal user chat text. "
    "To communicate with another agent you MUST call the tool `send_teammate_message` "
    "with parameters `to_agent`, `text`, and `from_agent` (your agent id). "
    "Optional `team_id` defaults to the session team. "
    "Incoming messages for you appear only via tool results or the Team panel in UI, "
    "not through the user's chat channel."
)
