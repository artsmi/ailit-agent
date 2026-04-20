"""Каталог провайдеров и известных моделей для CLI/TUI.

Важно: список моделей здесь *справочный* (не гарантирует полноту).
Рантайм принимает пользовательское имя модели через config/CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ProviderModelCatalog:
    """Справочник моделей одного провайдера."""

    provider_id: str
    models: tuple[str, ...]
    default_model: str


_DEEPSEEK: Final[ProviderModelCatalog] = ProviderModelCatalog(
    provider_id="deepseek",
    models=(
        "deepseek-chat",
        "deepseek-reasoner",
    ),
    default_model="deepseek-chat",
)

_KIMI: Final[ProviderModelCatalog] = ProviderModelCatalog(
    provider_id="kimi",
    models=(
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ),
    default_model="moonshot-v1-8k",
)

_MOCK: Final[ProviderModelCatalog] = ProviderModelCatalog(
    provider_id="mock",
    models=("mock",),
    default_model="mock",
)

PROVIDERS: Final[tuple[ProviderModelCatalog, ...]] = (
    _DEEPSEEK,
    _KIMI,
    _MOCK,
)


def provider_ids() -> tuple[str, ...]:
    """Идентификаторы провайдеров, известных CLI."""
    return tuple(p.provider_id for p in PROVIDERS)


def catalog_for(provider_id: str) -> ProviderModelCatalog | None:
    """Каталог для провайдера или None."""
    pid = provider_id.strip().lower()
    for p in PROVIDERS:
        if p.provider_id == pid:
            return p
    return None
