"""Бюджет сессии."""

from __future__ import annotations

from ailit_base.models import ChatMessage, MessageRole, NormalizedUsage
from agent_work.session.budget import BudgetGovernance


def test_context_units_exceeded() -> None:
    """Превышение max_context_units."""
    bud = BudgetGovernance(max_context_units=5)
    long_content = "x" * 100
    messages = [ChatMessage(role=MessageRole.USER, content=long_content)]
    assert bud.check_exceeded(messages) == "context_budget_exceeded"


def test_total_tokens_exceeded() -> None:
    """Превышение max_total_tokens по накопленному usage."""
    bud = BudgetGovernance(max_total_tokens=10)
    bud.record_usage(NormalizedUsage(6, 6, 12, usage_missing=False))
    assert bud.check_exceeded([]) == "token_budget_exceeded"
