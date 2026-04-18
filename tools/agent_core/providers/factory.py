"""Фабрика провайдеров по типу и локальному конфигу."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from agent_core.config_loader import (
    deepseek_api_key_from_env_or_config,
    kimi_api_key_from_env_or_config,
    load_test_local_yaml,
)
from agent_core.providers.deepseek import DeepSeekAdapter
from agent_core.providers.kimi import KimiAdapter
from agent_core.providers.mock_provider import MockProvider
from agent_core.providers.protocol import ChatProvider


class ProviderKind(str, Enum):
    """Дискретный выбор провайдера (конфиг/CLI)."""

    MOCK = "mock"
    KIMI = "kimi"
    DEEPSEEK = "deepseek"


class ProviderFactory:
    """Создание провайдера в одном месте."""

    @staticmethod
    def create(
        kind: ProviderKind,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> ChatProvider:
        """Собрать провайдер по виду и опциональному конфигу yaml."""
        cfg = dict(config or load_test_local_yaml())
        if kind is ProviderKind.MOCK:
            return MockProvider()
        if kind is ProviderKind.DEEPSEEK:
            key = deepseek_api_key_from_env_or_config(cfg)
            if not key:
                msg = "DeepSeek api key missing: set DEEPSEEK_API_KEY or config/test.local.yaml"
                raise ValueError(msg)
            ds = cfg.get("deepseek")
            root = "https://api.deepseek.com/v1"
            if isinstance(ds, dict):
                root = str(ds.get("base_url") or root).rstrip("/")
            return DeepSeekAdapter(key, api_root=root)
        if kind is ProviderKind.KIMI:
            key = kimi_api_key_from_env_or_config(cfg)
            if not key:
                msg = "Kimi api key missing: set KIMI_API_KEY or config/test.local.yaml"
                raise ValueError(msg)
            km = cfg.get("kimi")
            root = "https://api.moonshot.cn/v1"
            if isinstance(km, dict):
                root = str(km.get("base_url") or root).rstrip("/")
            return KimiAdapter(key, api_root=root)
        msg = f"unknown provider kind: {kind!r}"
        raise ValueError(msg)
