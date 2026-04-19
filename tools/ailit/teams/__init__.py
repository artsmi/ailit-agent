"""MVP межагентной почты (этап L.1): каталог ``teams/<team_id>/inboxes/*.json``."""

from __future__ import annotations

from ailit.teams.mailbox import TeamMessageRecord, TeamRootSelector, TeamSession

__all__ = [
    "TeamMessageRecord",
    "TeamRootSelector",
    "TeamSession",
]
