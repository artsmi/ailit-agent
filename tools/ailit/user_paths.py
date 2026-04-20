"""Канонические глобальные пути конфигурации и состояния для CLI и UI.

Порядок приоритета для **каталога конфигурации** (файл ``config.yaml``
внутри него, см. :mod:`ailit.merged_config`):

1. ``AILIT_CONFIG_DIR`` — полный override каталога конфигурации.
2. Иначе при заданном ``AILIT_HOME``: ``<AILIT_HOME>/config`` (дерево как у
   единого «дома» приложения; ориентир — ``CLAUDE_CONFIG_DIR`` /
   ``getClaudeConfigHomeDir`` в ``claude-code``, см. ``utils/envUtils.ts``).
3. Иначе XDG/дефолты: на POSIX ``XDG_CONFIG_HOME/ailit`` или
   ``~/.config/ailit``; на Windows ``%APPDATA%/ailit``.

Для **каталога состояния** (логи процессов, снимки TUI и т.п.):

1. ``AILIT_STATE_DIR``.
2. Иначе при ``AILIT_HOME``: ``<AILIT_HOME>/state``.
3. Иначе XDG: ``XDG_STATE_HOME/ailit`` или ``~/.local/state/ailit``;
   на Windows ``%LOCALAPPDATA%/ailit``.

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

    def global_config_dir(self) -> Path:
        """Каталог пользовательской конфигурации ``ailit``."""
        override = self._environ.get("AILIT_CONFIG_DIR")
        if override:
            return self._resolved_dir(override)
        home_root = self._environ.get("AILIT_HOME")
        if home_root:
            return (self._resolved_dir(home_root) / "config").resolve()
        return self._default_config_dir()

    def global_state_dir(self) -> Path:
        """Каталог пользовательского состояния (кэши, логи сессий и т.п.)."""
        override = self._environ.get("AILIT_STATE_DIR")
        if override:
            return self._resolved_dir(override)
        home_root = self._environ.get("AILIT_HOME")
        if home_root:
            return (self._resolved_dir(home_root) / "state").resolve()
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
    """Глобальный каталог конфигурации (см. ``GlobalDirResolver``)."""
    return GlobalDirResolver().global_config_dir()


def global_state_dir() -> Path:
    """Эффективный глобальный каталог состояния."""
    return GlobalDirResolver().global_state_dir()


def global_logs_dir() -> Path:
    """Каталог JSONL-логов процессов (chat/agent) внутри state."""
    return GlobalDirResolver().global_state_dir() / "logs"
