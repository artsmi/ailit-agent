"""Agent registry и capability/handlers registry (G8.1.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AgentRegistration:
    """Описание доступного агента и его обработчиков."""

    agent_type: str
    agent_instance_id: str
    chat_id: str
    capabilities: tuple[str, ...] = ()
    service_handlers: tuple[str, ...] = ()
    topic_subscriptions: tuple[str, ...] = ()
    action_handlers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "agent_instance_id": self.agent_instance_id,
            "chat_id": self.chat_id,
            "capabilities": list(self.capabilities),
            "service_handlers": list(self.service_handlers),
            "topic_subscriptions": list(self.topic_subscriptions),
            "action_handlers": list(self.action_handlers),
        }


@dataclass(slots=True)
class AgentRegistry:
    """Реестр агентов для broker и UI."""

    _agents: dict[str, AgentRegistration] = field(default_factory=dict)

    def register(self, reg: AgentRegistration) -> None:
        """Зарегистрировать/обновить агента."""
        key = self._key(reg.chat_id, reg.agent_instance_id)
        self._agents[key] = reg

    def remove(self, *, chat_id: str, agent_instance_id: str) -> None:
        """Удалить агента."""
        key = self._key(chat_id, agent_instance_id)
        self._agents.pop(key, None)

    def list_agents(
        self,
        *,
        chat_id: str | None = None,
    ) -> tuple[AgentRegistration, ...]:
        """Список зарегистрированных агентов (опционально по chat_id)."""
        if chat_id is None:
            return tuple(self._agents.values())
        return tuple(v for v in self._agents.values() if v.chat_id == chat_id)

    def describe(self, *, chat_id: str | None = None) -> Mapping[str, Any]:
        """Экспорт для UI/broker."""
        agents = self.list_agents(chat_id=chat_id)
        return {"agents": [a.to_dict() for a in agents]}

    @staticmethod
    def _key(chat_id: str, agent_instance_id: str) -> str:
        return f"{chat_id}:{agent_instance_id}"
