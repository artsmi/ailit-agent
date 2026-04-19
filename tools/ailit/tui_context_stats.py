"""Форматирование usage для TUI: подпись и таблица ``/ctx stats`` (Q.2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ailit.tui_context_manager import TuiContextManager


@dataclass(frozen=True, slots=True)
class _TokenSnapshot:
    """Снимок счётчиков для одной строки таблицы."""

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> _TokenSnapshot:
        """Собрать из ``UsageTotals.as_dict()`` или ``usage`` ответа."""
        return cls(
            input_tokens=int(d.get("input_tokens") or 0),
            output_tokens=int(d.get("output_tokens") or 0),
            reasoning_tokens=int(d.get("reasoning_tokens") or 0),
            cache_read_tokens=int(d.get("cache_read_tokens") or 0),
            cache_write_tokens=int(d.get("cache_write_tokens") or 0),
        )


@dataclass(frozen=True, slots=True)
class CtxUsageMarkdownTable:
    """Markdown-таблица накопленного usage по всем контекстам."""

    def render_lines(self, mgr: TuiContextManager) -> tuple[str, ...]:
        """Строки для вывода в ``RichLog`` (без HTML-экранирования)."""
        rows = mgr.all_usage_rows()
        if not rows:
            return ("Нет контекстов.",)
        header = (
            "| context | in | out | reason | cache_r | cache_w |",
            "|---|---:|---:|---:|---:|---:|",
        )
        body: list[str] = []
        for name, d in rows:
            snap = _TokenSnapshot.from_mapping(d)
            act = " *" if name == mgr.active_name() else ""
            row = (
                f"| `{name}`{act} | {snap.input_tokens} | "
                f"{snap.output_tokens} | {snap.reasoning_tokens} | "
                f"{snap.cache_read_tokens} | {snap.cache_write_tokens} |"
            )
            body.append(row)
        return ("Накопленные токены по контекстам:", *header, *body)


@dataclass(frozen=True, slots=True)
class TuiSubtitleUsageFormatter:
    """Подзаголовок: активный контекст, последний ход и Σ по контексту."""

    def format_idle(
        self,
        *,
        context_name: str,
        cumulative: Mapping[str, Any],
        provider: str,
        model: str,
        max_turns: int,
    ) -> str:
        """Состояние без только что завершённого хода."""
        c = _TokenSnapshot.from_mapping(cumulative)
        core = (
            f"{context_name} | Σ in={c.input_tokens} out={c.output_tokens} "
            f"cr={c.cache_read_tokens} cw={c.cache_write_tokens}"
        )
        return f"{core} | {provider} | {model} | mt={max_turns}"[:220]

    def format_after_turn(
        self,
        *,
        context_name: str,
        last_turn: Mapping[str, Any] | None,
        cumulative: Mapping[str, Any],
        provider: str,
        model: str,
        max_turns: int,
    ) -> str:
        """После ответа модели: last + накопление по активному контексту."""
        c = _TokenSnapshot.from_mapping(cumulative)
        base = (
            f"{context_name} | Σ in={c.input_tokens} out={c.output_tokens} "
            f"cr={c.cache_read_tokens} cw={c.cache_write_tokens}"
        )
        if last_turn and not last_turn.get("usage_missing"):
            lt = _TokenSnapshot.from_mapping(last_turn)
            last = (
                f"last in={lt.input_tokens} out={lt.output_tokens} "
                f"cr={lt.cache_read_tokens} cw={lt.cache_write_tokens}"
            )
            tail = f"{provider} | {model} | mt={max_turns}"
            return f"{base} | {last} | {tail}"[:220]
        tail = f"{provider} | {model} | mt={max_turns}"
        return f"{base} | {tail}"[:220]
