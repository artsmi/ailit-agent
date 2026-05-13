"""Ошибки runtime contract и локального транспорта."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeProtocolError(Exception):
    """Ошибка протокола runtime (decode/validate)."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
