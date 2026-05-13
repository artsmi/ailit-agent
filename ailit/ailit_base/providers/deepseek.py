"""Адаптер DeepSeek (OpenAI-совместимый endpoint)."""

from __future__ import annotations

from ailit_base.providers.openai_compat import OpenAICompatProvider
from ailit_base.transport.httpx_transport import HttpxJsonTransport


class DeepSeekAdapter(OpenAICompatProvider):
    """Провайдер DeepSeek."""

    def __init__(
        self,
        api_key: str,
        *,
        api_root: str = "https://api.deepseek.com/v1",
        transport: HttpxJsonTransport | None = None,
    ) -> None:
        """Создать адаптер с ключом и корнем API."""
        super().__init__(
            provider_id="deepseek",
            api_root=api_root,
            api_key=api_key,
            transport=transport,
        )
