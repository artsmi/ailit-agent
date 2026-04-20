"""Проекция истории чата для UI.

Без сырых TOOL; компактные шаги по tool_calls.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.models import ChatMessage, MessageRole
from agent_core.normalization.content_sanitize import AssistantContentSanitizer


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    """Строка UI: роль и markdown."""

    role: MessageRole
    markdown: str


class ChatTranscriptProjector:
    """Строит линии транскрипта без payload инструментов."""

    def project(
        self,
        messages: Sequence[ChatMessage],
    ) -> tuple[TranscriptLine, ...]:
        """Спрятать SYSTEM/TOOL; шаги assistant без аргументов tools."""
        out: list[TranscriptLine] = []
        for msg in messages:
            if msg.role is MessageRole.SYSTEM:
                continue
            if msg.role is MessageRole.TOOL:
                continue
            if msg.role is MessageRole.USER:
                out.append(
                    TranscriptLine(
                        role=MessageRole.USER,
                        markdown=msg.content if msg.content else " ",
                    ),
                )
                continue
            if msg.role is not MessageRole.ASSISTANT:
                continue
            tcalls = msg.tool_calls or ()
            for tc in tcalls:
                name = tc.tool_name.strip() or "?"
                out.append(
                    TranscriptLine(
                        role=MessageRole.ASSISTANT,
                        markdown=f"_Шаг:_ вызван `{name}`",
                    ),
                )
            stripped = (msg.content or "").strip()
            aggressive_tail = bool(tcalls) or ("dsml" in stripped.lower())
            body = (
                AssistantContentSanitizer.sanitize(
                    stripped,
                    aggressive_trailing=aggressive_tail,
                )
                if stripped
                else ""
            )
            if body:
                out.append(
                    TranscriptLine(role=MessageRole.ASSISTANT, markdown=body),
                )
            elif not tcalls:
                out.append(
                    TranscriptLine(role=MessageRole.ASSISTANT, markdown=" "),
                )
        return tuple(out)
