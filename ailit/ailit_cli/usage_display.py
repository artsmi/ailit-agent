"""Единое отображение usage для Streamlit и CLI (этап O)."""

from __future__ import annotations

import json
from typing import Any, Mapping


def _fmt_int(val: Any) -> str:
    """Число или прочерк."""
    if val is None:
        return "—"
    if isinstance(val, bool):
        return str(int(val))
    if isinstance(val, int):
        return str(val)
    try:
        return str(int(val))
    except (TypeError, ValueError):
        return "—"


class SessionEventsUsageExtractor:
    """Последний ``usage`` и ``usage_session_totals`` из событий сессии."""

    @staticmethod
    def last_pair(
        events: tuple[Mapping[str, Any], ...],
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Вернуть (usage, usage_session_totals) или None."""
        for row in reversed(events):
            if row.get("event_type") != "model.response":
                continue
            u = row.get("usage")
            t = row.get("usage_session_totals")
            if isinstance(u, dict) and isinstance(t, dict):
                return dict(u), dict(t)
        return None


class UsageSummaryMarkdownFormatter:
    """Компактные строки и markdown для панели «токены»."""

    def compact_session_line(self, totals: Mapping[str, Any]) -> str:
        """Одна строка: накопленно за прогон session loop."""
        parts = [
            f"in **{_fmt_int(totals.get('input_tokens'))}**",
            f"out **{_fmt_int(totals.get('output_tokens'))}**",
        ]
        r = totals.get("reasoning_tokens")
        if r is not None and int(r or 0) > 0:
            parts.append(f"reasoning **{_fmt_int(r)}**")
        cr = totals.get("cache_read_tokens")
        cw = totals.get("cache_write_tokens")
        if cr is not None or cw is not None:
            parts.append(f"cache read **{_fmt_int(cr)}**")
            parts.append(f"cache write **{_fmt_int(cw)}**")
        inner = " · ".join(parts)
        tot = totals.get("total_tokens")
        suffix = f" (Σ in+out **{_fmt_int(tot)}**)" if tot is not None else ""
        return f"Накопленно за сессию: {inner}{suffix}"

    def compact_last_call_line(self, usage: Mapping[str, Any]) -> str:
        """Одна строка: последний ответ модели."""
        if usage.get("usage_missing"):
            return "Последний вызов: usage **нет** в ответе провайдера."
        parts = [
            f"in **{_fmt_int(usage.get('input_tokens'))}**",
            f"out **{_fmt_int(usage.get('output_tokens'))}**",
        ]
        rt = usage.get("reasoning_tokens")
        if rt is not None:
            parts.append(f"reasoning **{_fmt_int(rt)}**")
        cr = usage.get("cache_read_tokens")
        cw = usage.get("cache_write_tokens")
        if cr is not None or cw is not None:
            parts.append(f"cache read **{_fmt_int(cr)}**")
            parts.append(f"cache write **{_fmt_int(cw)}**")
        unk = usage.get("usage_unknown")
        if isinstance(unk, dict) and unk:
            parts.append(f"+{len(unk)} неизв. полей")
        return "Последний вызов модели: " + " · ".join(parts)

    def expander_markdown(
        self,
        *,
        last_usage: Mapping[str, Any],
        session_totals: Mapping[str, Any],
    ) -> str:
        """Подробности для expander."""
        lines = [
            "### Накопленно (session loop)",
            "",
            f"```json\n{_pretty_json(session_totals)}\n```",
            "",
            "### Последний ответ модели",
            "",
            f"```json\n{_pretty_json(last_usage)}\n```",
        ]
        return "\n".join(lines)


def _pretty_json(obj: Mapping[str, Any]) -> str:
    """Компактный JSON для markdown code block."""
    return json.dumps(dict(obj), ensure_ascii=False, indent=2)


class UsageSummaryPlainTextFormatter:
    """Те же числа без markdown (CLI)."""

    def __init__(
        self,
        *,
        inner: UsageSummaryMarkdownFormatter | None = None,
    ) -> None:
        """Делегирование в ``UsageSummaryMarkdownFormatter``."""
        self._inner = inner or UsageSummaryMarkdownFormatter()

    def format_block(
        self,
        *,
        last_usage: Mapping[str, Any],
        session_totals: Mapping[str, Any],
    ) -> str:
        """Плоский текст для stdout."""
        a = self._inner.compact_last_call_line(last_usage)
        b = self._inner.compact_session_line(session_totals)
        return f"{a}\n{b}\n"
