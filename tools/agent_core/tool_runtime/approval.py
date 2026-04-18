"""Сессионные решения по запросам approval (pause/resume)."""

from __future__ import annotations

from enum import Enum


class ApprovalDecision(str, Enum):
    """Итог по конкретному call_id."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalSession:
    """Хранит решения оператора по tool_call_id."""

    def __init__(self) -> None:
        """Создать пустую сессию."""
        self._decisions: dict[str, ApprovalDecision] = {}

    def status(self, call_id: str) -> ApprovalDecision:
        """Текущий статус по идентификатору вызова."""
        return self._decisions.get(call_id, ApprovalDecision.PENDING)

    def approve(self, call_id: str) -> None:
        """Зафиксировать одобрение (идемпотентно)."""
        self._decisions[call_id] = ApprovalDecision.APPROVED

    def reject(self, call_id: str) -> None:
        """Зафиксировать отказ."""
        self._decisions[call_id] = ApprovalDecision.REJECTED

    def is_approved(self, call_id: str) -> bool:
        """True если вызов одобрен."""
        return self.status(call_id) is ApprovalDecision.APPROVED

    def is_rejected(self, call_id: str) -> bool:
        """True если вызов отклонён."""
        return self.status(call_id) is ApprovalDecision.REJECTED

    def clear(self, call_id: str) -> None:
        """Сбросить решение (для тестов)."""
        self._decisions.pop(call_id, None)
