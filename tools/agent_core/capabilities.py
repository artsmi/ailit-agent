"""Capability matrix и проверки для провайдеров."""

from __future__ import annotations

from enum import Enum
from typing import Final


class Capability(str, Enum):
    """Возможности провайдера (выбор по capability, не по бренду)."""

    CHAT = "chat"
    STREAMING = "streaming"
    TOOLS = "tools"
    STRICT_SCHEMA = "strict_schema"
    USAGE = "usage"
    PARSER_FALLBACK = "parser_fallback"


# Единственное место сопоставления бренда и capability (этап 3).
_CAPABILITY_MATRIX: Final[dict[str, frozenset[Capability]]] = {
    "mock": frozenset(
        {
            Capability.CHAT,
            Capability.STREAMING,
            Capability.TOOLS,
            Capability.STRICT_SCHEMA,
            Capability.USAGE,
            Capability.PARSER_FALLBACK,
        }
    ),
    "kimi": frozenset(
        {
            Capability.CHAT,
            Capability.STREAMING,
            Capability.TOOLS,
            Capability.USAGE,
            Capability.PARSER_FALLBACK,
            # strict schema — ограниченно, оставляем выключенным в матрице
        }
    ),
    "deepseek": frozenset(
        {
            Capability.CHAT,
            Capability.STREAMING,
            Capability.TOOLS,
            Capability.STRICT_SCHEMA,
            Capability.USAGE,
            Capability.PARSER_FALLBACK,
        }
    ),
}


def capability_set_for(provider_id: str) -> frozenset[Capability]:
    """Вернуть набор capability для идентификатора провайдера."""
    key = provider_id.lower().strip()
    if key not in _CAPABILITY_MATRIX:
        return frozenset({Capability.CHAT})
    return _CAPABILITY_MATRIX[key]


def provider_supports(provider_id: str, capability: Capability) -> bool:
    """Проверить, заявлена ли capability для провайдера."""
    return capability in capability_set_for(provider_id)


def require_capability(provider_id: str, capability: Capability) -> None:
    """Бросить ValueError, если capability не поддерживается."""
    if not provider_supports(provider_id, capability):
        msg = f"provider {provider_id!r} does not support {capability.value}"
        raise ValueError(msg)
