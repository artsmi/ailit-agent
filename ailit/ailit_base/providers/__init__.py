"""Провайдеры чата: протокол, mock, OpenAI-совместимые адаптеры."""

from ailit_base.providers.deepseek import DeepSeekAdapter
from ailit_base.providers.factory import ProviderFactory, ProviderKind
from ailit_base.providers.kimi import KimiAdapter
from ailit_base.providers.mock_provider import MockProvider
from ailit_base.providers.protocol import ChatProvider

__all__ = [
    "ChatProvider",
    "DeepSeekAdapter",
    "KimiAdapter",
    "MockProvider",
    "ProviderFactory",
    "ProviderKind",
]
