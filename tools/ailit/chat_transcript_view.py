"""Проекция истории чата для UI.

Без сырых TOOL; шаги инструментов сворачиваются в одну строку-сводку;
текст финального ответа — с переносами между предложениями.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.models import ChatMessage, MessageRole
from agent_core.normalization.content_sanitize import AssistantContentSanitizer


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    """Строка UI: роль и markdown."""

    role: MessageRole
    markdown: str


class TrailingColonEllipsisFormatter:
    """Хвостовое «:» (артефакт стрима) заменить на «…».

    URL с ``://`` в хвосте не трогаем.
    """

    def format(self, text: str) -> str:
        """Заменить финальное «:» на «…» при необходимости."""
        if not text:
            return text
        stripped = text.rstrip(" \t")
        suffix_ws = text[len(stripped):]
        if not stripped.endswith(":"):
            return text
        if "://" in stripped[-40:]:
            return text
        return stripped[:-1] + "…" + suffix_ws


class SentenceBreakFormatter:
    """Вставляет пустую строку между «слепленными» фразами в потоке ответа."""

    # Пробел после знака, затем заглавная (RU/EN).
    _spaced = re.compile(r"([.!?])(\s+)([А-ЯЁA-Z])")
    _tight = re.compile(r"([.!?])([А-ЯЁA-Z])")
    # «…описание:Теперь» — типичный стиль моделей без перевода строки.
    _lower_then_colon_cap = re.compile(
        r"([a-zа-яё])(:)([А-ЯЁA-Z])",
    )
    # Двоеточие + пробел + заглавная.
    _colon_spaced_cap = re.compile(
        r"(:)(\s+)([А-ЯЁA-Z])",
    )
    _collapse = re.compile(r"\n{3,}")

    def format(self, text: str) -> str:
        """Разбить склейки вроде «…:Теперь» для markdown-абзацев."""
        if not text.strip():
            return text
        t = self._spaced.sub(r"\1\n\n\3", text)
        t = self._tight.sub(r"\1\n\n\2", t)
        t = self._lower_then_colon_cap.sub(r"\1\2\n\n\3", t)
        t = self._colon_spaced_cap.sub(r"\1\n\n\3", t)
        return self._collapse.sub("\n\n", t).strip()


class AssistantDisplayFormatter:
    """Санитайз DSML + разбиение на абзацы по предложениям."""

    def __init__(self) -> None:
        """Подготовить вложенный форматтер."""
        self._breaks = SentenceBreakFormatter()
        self._colon_tail = TrailingColonEllipsisFormatter()

    def format(self, text: str, *, aggressive_tail: bool) -> str:
        """Текст для отображения пользователю."""
        stripped = text.strip()
        if not stripped:
            return ""
        clean = AssistantContentSanitizer.sanitize(
            stripped,
            aggressive_trailing=aggressive_tail,
        )
        clean = self._colon_tail.format(clean)
        return self._breaks.format(clean)


class ToolInvocationSummaryFormatter:
    """Одна строка-сводка по списку вызовов (с учётом повторов)."""

    _glyph = "〔∴〕"

    def line(self, ordered_names: list[str]) -> str:
        """Markdown: курсивная строка со знаком сводки и списком имён."""
        if not ordered_names:
            return ""
        counts: Counter[str] = Counter(ordered_names)
        order_unique: list[str] = []
        seen: set[str] = set()
        for name in ordered_names:
            if name not in seen:
                seen.add(name)
                order_unique.append(name)
        parts: list[str] = []
        for name in order_unique:
            n = counts[name]
            if n > 1:
                parts.append(f"`{name}` ×{n}")
            else:
                parts.append(f"`{name}`")
        joined = ", ".join(parts)
        return f"_{self._glyph} Сводка инструментов: {joined}._"


_fmt = AssistantDisplayFormatter()
_summary = ToolInvocationSummaryFormatter()


def format_assistant_body_for_ui(text: str, *, aggressive_tail: bool) -> str:
    """Публичная обёртка для Streamlit/TUI (санитайз + переносы)."""
    return _fmt.format(text, aggressive_tail=aggressive_tail)


def format_tool_summary_markdown(ordered_tool_names: list[str]) -> str:
    """Одна строка сводки по именам в порядке первых появлений."""
    return _summary.line(ordered_tool_names)


class ChatTranscriptProjector:
    """Строит линии транскрипта: USER → сводка tools → финальный текст хода."""

    def __init__(self) -> None:
        """Собрать форматтеры."""
        self._display = AssistantDisplayFormatter()
        self._tools = ToolInvocationSummaryFormatter()

    def project(
        self,
        messages: Sequence[ChatMessage],
    ) -> tuple[TranscriptLine, ...]:
        """Спрятать SYSTEM/TOOL; свернуть шаги одного USER-хода."""
        raw = list(messages)
        out: list[TranscriptLine] = []
        i = 0
        while i < len(raw):
            msg = raw[i]
            if msg.role is MessageRole.SYSTEM:
                i += 1
                continue
            if msg.role is MessageRole.TOOL:
                i += 1
                continue
            if msg.role is MessageRole.USER:
                out.append(
                    TranscriptLine(
                        role=MessageRole.USER,
                        markdown=msg.content if msg.content else " ",
                    ),
                )
                i += 1
                seq, i = self._consume_assistant_run(raw, i)
                self._emit_turn(out, seq)
                continue
            if msg.role is MessageRole.ASSISTANT:
                seq, i = self._consume_assistant_run(raw, i)
                self._emit_turn(out, seq)
                continue
            i += 1
        return tuple(out)

    def _consume_assistant_run(
        self,
        raw: list[ChatMessage],
        start: int,
    ) -> tuple[list[ChatMessage], int]:
        """Assistant до user/system; TOOL пропускаем; j — след. индекс."""
        seq: list[ChatMessage] = []
        j = start
        while j < len(raw):
            m = raw[j]
            if m.role in (MessageRole.USER, MessageRole.SYSTEM):
                break
            if m.role is MessageRole.TOOL:
                j += 1
                continue
            if m.role is MessageRole.ASSISTANT:
                seq.append(m)
                j += 1
                continue
            break
        return seq, j

    def _emit_turn(
        self,
        out: list[TranscriptLine],
        seq: list[ChatMessage],
    ) -> None:
        """Одна «волна» assistant: сводка инструментов + финальный текст."""
        if not seq:
            return
        names: list[str] = []
        for a in seq:
            for tc in a.tool_calls or ():
                n = tc.tool_name.strip() or "?"
                names.append(n)
        final_msg: ChatMessage | None = None
        for a in reversed(seq):
            if not a.tool_calls:
                final_msg = a
                break
        if final_msg is None:
            final_msg = seq[-1]
        if names:
            out.append(
                TranscriptLine(
                    role=MessageRole.ASSISTANT,
                    markdown=self._tools.line(names),
                ),
            )
        stripped = (final_msg.content or "").strip()
        aggressive = bool(final_msg.tool_calls) or (
            "dsml" in stripped.lower()
        )
        body = (
            self._display.format(stripped, aggressive_tail=aggressive)
            if stripped
            else ""
        )
        if body:
            out.append(
                TranscriptLine(role=MessageRole.ASSISTANT, markdown=body),
            )
        elif not names:
            out.append(
                TranscriptLine(role=MessageRole.ASSISTANT, markdown=" "),
            )
