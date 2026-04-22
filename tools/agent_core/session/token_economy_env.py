"""Общие флаги env для pager / budget / prune (по умолчанию включено)."""

from __future__ import annotations

import os

__all__ = [
    "env_flag",
    "token_economy_globally_disabled",
]


def token_economy_globally_disabled() -> bool:
    """`AILIT_TOKEN_ECONOMY=0` — отключить все механизмы token-economy."""
    v = os.environ.get("AILIT_TOKEN_ECONOMY", "").strip().lower()
    return v in ("0", "false", "off", "no")


def env_flag(
    name: str,
    *,
    default: bool = True,
) -> bool:
    """Переменная: пусто → default, 0/false → False, 1/true → True."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("0", "false", "off", "no"):
        return False
    if raw in ("1", "true", "on", "yes"):
        return True
    return default
