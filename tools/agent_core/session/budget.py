"""Накопление usage и проверка бюджетов (MVP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from agent_core.models import ChatMessage, NormalizedUsage


@dataclass
class BudgetGovernance:
    """Ограничения по токенам и грубой оценке размера контекста."""

    max_total_tokens: int | None = None
    max_context_units: int | None = None
    _acc_input: int = field(default=0, init=False, repr=False)
    _acc_output: int = field(default=0, init=False, repr=False)

    def reset(self) -> None:
        """Сбросить накопленный usage."""
        self._acc_input = 0
        self._acc_output = 0

    def record_usage(self, usage: NormalizedUsage) -> None:
        """Добавить usage одного ответа модели."""
        if usage.usage_missing:
            return
        self._acc_input += int(usage.input_tokens or 0)
        self._acc_output += int(usage.output_tokens or 0)

    def total_recorded(self) -> int:
        """Сумма зарегистрированных input+output."""
        return self._acc_input + self._acc_output

    @staticmethod
    def estimate_context_units(messages: Sequence[ChatMessage]) -> int:
        """Грубая оценка «юнитов» контекста (~ токены/4)."""
        units = 0
        for m in messages:
            units += max(1, len(m.content) // 4)
            if m.tool_calls:
                for tc in m.tool_calls:
                    units += max(1, len(tc.arguments_json) // 4)
        return units

    def check_exceeded(self, messages: Sequence[ChatMessage]) -> str | None:
        """Вернуть код причины превышения или None."""
        if self.max_context_units is not None:
            if self.estimate_context_units(messages) > self.max_context_units:
                return "context_budget_exceeded"
        if self.max_total_tokens is not None:
            if self.total_recorded() > self.max_total_tokens:
                return "token_budget_exceeded"
        return None
