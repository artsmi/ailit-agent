"""Счётчик итераций session loop из событий прогона (для подписи в UI)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChatSessionTurnProgress:
    """Число ``session.turn`` в прогоне относительно лимита ``max_turns``."""

    used_steps: int
    limit: int

    @classmethod
    def from_outcome_events(
        cls,
        events: tuple[dict[str, Any], ...],
        *,
        limit: int,
    ) -> ChatSessionTurnProgress:
        """Посчитать по кортежу ``SessionOutcome.events``."""
        used = sum(
            1 for row in events if row.get("event_type") == "session.turn"
        )
        return cls(used_steps=used, limit=limit)

    def short_label_ru(self) -> str:
        """Плейн-текст для caption (без markdown)."""
        return f"ход {self.used_steps} из {self.limit}"

    def markdown_caption(self) -> str:
        """Подпись для expander (markdown)."""
        return (
            f"**Ход {self.used_steps} из {self.limit}** — итерации "
            f"агентского цикла (лимит **max_turns** = {self.limit})."
        )
