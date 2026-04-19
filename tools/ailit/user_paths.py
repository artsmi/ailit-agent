"""Канонические глобальные пути конфигурации и состояния для CLI и UI.

Порядок приоритета для каталога конфигурации:
1. Переменная ``AILIT_CONFIG_DIR`` (полный override).
2. На POSIX: ``XDG_CONFIG_HOME/ailit`` или ``~/.config/ailit``.
3. На Windows: ``%APPDATA%/ailit`` (или домашний ``AppData/Roaming/ailit``).

Для каталога состояния:
1. ``AILIT_STATE_DIR`` при наличии.
2. На POSIX: ``XDG_STATE_HOME/ailit`` или ``~/.local/state/ailit``.
3. На Windows: ``%LOCALAPPDATA%/ailit``.
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

    def global_config_dir(self) -> Path:
        """Каталог пользовательской конфигурации ``ailit``."""
        override = self._environ.get("AILIT_CONFIG_DIR")
        if override:
            return self._resolved_dir(override)
        return self._default_config_dir()

    def global_state_dir(self) -> Path:
        """Каталог пользовательского состояния (кэши, логи сессий и т.п.)."""
        override = self._environ.get("AILIT_STATE_DIR")
        if override:
            return self._resolved_dir(override)
        return self._default_state_dir()

    def _default_config_dir(self) -> Path:
        if os.name == "nt":
            appdata = self._environ.get("APPDATA")
            if appdata:
                return (Path(appdata) / "ailit").resolve()
            home = Path.home()
            return (home / "AppData" / "Roaming" / "ailit").resolve()
        xdg = self._environ.get("XDG_CONFIG_HOME")
        if xdg:
            return (Path(xdg).expanduser() / "ailit").resolve()
        return (Path.home() / ".config" / "ailit").resolve()

    def _default_state_dir(self) -> Path:
        if os.name == "nt":
            local = self._environ.get("LOCALAPPDATA")
            if local:
                return (Path(local) / "ailit").resolve()
            home = Path.home()
            return (home / "AppData" / "Local" / "ailit").resolve()
        xdg = self._environ.get("XDG_STATE_HOME")
        if xdg:
            return (Path(xdg).expanduser() / "ailit").resolve()
        return (Path.home() / ".local" / "state" / "ailit").resolve()


def global_config_dir() -> Path:
    """Эффективный глобальный каталог конфигурации (см. :class:`GlobalDirResolver`)."""
    return GlobalDirResolver().global_config_dir()


def global_state_dir() -> Path:
    """Эффективный глобальный каталог состояния."""
    return GlobalDirResolver().global_state_dir()
