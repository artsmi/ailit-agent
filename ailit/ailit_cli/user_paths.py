"""Канонические глобальные пути конфигурации и состояния для CLI и UI.

Цель: **один глобальный дом** для всех файлов `ailit` по умолчанию.

Базовый каталог (``ailit_home``):

- ``AILIT_HOME`` если задан.
- иначе ``~/.ailit`` (POSIX и Windows, если нет явных override).

Иерархия внутри ``ailit_home``:

- ``config/`` — конфигурация пользователя
- ``state/`` — состояние, логи и кэши
  - ``state/logs/`` — JSONL-логи процессов (chat/agent)
  - ``state/tui-sessions/`` — сохранённые сессии TUI

Override-переменные (сильнее ``AILIT_HOME``):

- ``AILIT_CONFIG_DIR`` — полный override каталога конфигурации.
- ``AILIT_STATE_DIR`` — полный override каталога состояния.

Слой merge ключей конфигурации описан в :mod:`ailit.config_layer_order`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


class GlobalDirResolver:
    """Определяет глобальные каталоги без привязки к корню репозитория."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        """Инициализировать резолвер.

        Args:
            environ: Карта переменных окружения; по умолчанию ``os.environ``.
        """
        self._environ: Mapping[str, str] = (
            environ if environ is not None else os.environ
        )

    @staticmethod
    def _resolved_dir(raw: str) -> Path:
        return Path(raw).expanduser().resolve()

    def _default_ailit_home(self) -> Path:
        """Дефолтный глобальный дом: ``~/.ailit``."""
        return (Path.home() / ".ailit").resolve()

    def ailit_home(self) -> Path:
        """Глобальный дом пользователя (единый корень для config/state)."""
        home_root = self._environ.get("AILIT_HOME")
        if home_root:
            return self._resolved_dir(home_root)
        return self._default_ailit_home()

    def global_config_dir(self) -> Path:
        """Каталог пользовательской конфигурации ``ailit``."""
        override = self._environ.get("AILIT_CONFIG_DIR")
        if override:
            return self._resolved_dir(override)
        return (self.ailit_home() / "config").resolve()

    def global_state_dir(self) -> Path:
        """Каталог пользовательского состояния (кэши, логи сессий и т.п.)."""
        override = self._environ.get("AILIT_STATE_DIR")
        if override:
            return self._resolved_dir(override)
        return (self.ailit_home() / "state").resolve()


def global_config_dir() -> Path:
    """Глобальный каталог конфигурации (см. ``GlobalDirResolver``)."""
    return GlobalDirResolver().global_config_dir()


def global_state_dir() -> Path:
    """Эффективный глобальный каталог состояния."""
    return GlobalDirResolver().global_state_dir()


def global_logs_dir() -> Path:
    """Каталог JSONL-логов процессов (chat/agent) внутри state."""
    return GlobalDirResolver().global_state_dir() / "logs"
