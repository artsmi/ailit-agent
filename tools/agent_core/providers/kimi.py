"""Адаптер Kimi / Moonshot (OpenAI-совместимый endpoint)."""

from __future__ import annotations

from agent_core.providers.openai_compat import OpenAICompatProvider
from agent_core.transport.httpx_transport import HttpxJsonTransport


class KimiAdapter(OpenAICompatProvider):
    """Провайдер Kimi K2 через Moonshot OpenAI-совместимый API."""

    def __init__(
        self,
        api_key: str,
        *,
        api_root: str = "https://api.moonshot.cn/v1",
        transport: HttpxJsonTransport | None = None,
    ) -> None:
        """Создать адаптер с ключом и корнем API."""
        super().__init__(
            provider_id="kimi",
            api_root=api_root,
            api_key=api_key,
            transport=transport,
        )
