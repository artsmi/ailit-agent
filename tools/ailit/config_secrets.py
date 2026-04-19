"""Скрытие секретов в структурах конфигурации перед выводом в stdout."""

from __future__ import annotations

from typing import Any


class ConfigSecretRedactor:
    """Рекурсивно заменяет значения у чувствительных ключей."""

    _SENSITIVE_SUBSTRINGS: tuple[str, ...] = (
        "api_key",
        "apikey",
        "secret",
        "password",
        "token",
    )

    def redact(self, data: Any) -> Any:
        """Вернуть копию структуры с замаскированными секретами."""
        if isinstance(data, dict):
            out: dict[str, Any] = {}
            for key, value in data.items():
                key_l = str(key).lower()
                if self._is_sensitive_key(key_l):
                    out[key] = "***REDACTED***"
                else:
                    out[key] = self.redact(value)
            return out
        if isinstance(data, list):
            return [self.redact(item) for item in data]
        return data

    def _is_sensitive_key(self, key_lower: str) -> bool:
        return any(s in key_lower for s in self._SENSITIVE_SUBSTRINGS)
