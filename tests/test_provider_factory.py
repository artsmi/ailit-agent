"""Переключение провайдера через фабрику."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ailit_base.providers.factory import ProviderFactory, ProviderKind


def test_factory_mock() -> None:
    """MOCK всегда доступен."""
    p = ProviderFactory.create(ProviderKind.MOCK, config={})
    assert p.provider_id == "mock"


@patch(
    "ailit_base.providers.factory.deepseek_api_key_from_env_or_config",
    return_value="",
)
def test_factory_deepseek_requires_key(_mock_key: object) -> None:
    """Без ключа DeepSeek не создаётся."""
    with pytest.raises(ValueError, match="DeepSeek api key"):
        ProviderFactory.create(ProviderKind.DEEPSEEK, config={})


@patch(
    "ailit_base.providers.factory.deepseek_api_key_from_env_or_config",
    return_value="k",
)
def test_factory_deepseek_normalizes_base_url_v1(_mock_key: object) -> None:
    """base_url без /v1 нормализуется до /v1."""
    p = ProviderFactory.create(
        ProviderKind.DEEPSEEK,
        config={"deepseek": {"base_url": "https://api.deepseek.com"}},
    )
    assert getattr(p, "_api_root", "").endswith("/v1")
