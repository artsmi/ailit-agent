"""Секция project.yaml ``bash:`` → env для ``run_shell``."""

from __future__ import annotations

import json
import os
from typing import Final

from project_layer.models import BashSectionModel, BashSessionSectionModel

_ENV_KEYS: Final[tuple[str, ...]] = (
    "AILIT_BASH_DEFAULT_TIMEOUT_MS",
    "AILIT_BASH_MAX_CAPTURE_BYTES",
    "AILIT_BASH_ALLOW_PATTERNS_JSON",
    "AILIT_BASH_SESSION_IDLE_TIMEOUT_MS",
    "AILIT_BASH_SESSION_MAX_SESSIONS",
)


class BashProjectEnvSync:
    """Переменные окружения, которые читает ``builtin_run_shell``."""

    @staticmethod
    def clear() -> None:
        """Снять override bash из окружения (нет Shell / смена проекта)."""
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    @staticmethod
    def apply(section: BashSectionModel | None) -> None:
        """Применить секцию ``bash`` или только очистить override."""
        BashProjectEnvSync.clear()
        if section is None:
            return
        if section.default_timeout_ms is not None:
            os.environ["AILIT_BASH_DEFAULT_TIMEOUT_MS"] = str(
                int(section.default_timeout_ms),
            )
        if section.max_output_mb is not None:
            mb = float(section.max_output_mb)
            if mb <= 0:
                msg = "bash.max_output_mb must be > 0 when set"
                raise ValueError(msg)
            cap = int(mb * 1024 * 1024)
            if cap < 1:
                cap = 1
            os.environ["AILIT_BASH_MAX_CAPTURE_BYTES"] = str(cap)
        if section.allow_patterns:
            os.environ["AILIT_BASH_ALLOW_PATTERNS_JSON"] = json.dumps(
                list(section.allow_patterns),
                ensure_ascii=False,
            )


class BashSessionProjectEnvSync:
    """Секция project.yaml ``bash_session:`` → env для session manager."""

    @staticmethod
    def clear() -> None:
        """Снять override для bash session."""
        for key in (
            "AILIT_BASH_SESSION_IDLE_TIMEOUT_MS",
            "AILIT_BASH_SESSION_MAX_SESSIONS",
        ):
            os.environ.pop(key, None)

    @staticmethod
    def apply(section: BashSessionSectionModel | None) -> None:
        """Применить секцию ``bash_session`` или очистить override."""
        BashSessionProjectEnvSync.clear()
        if section is None:
            return
        if section.idle_timeout_ms is not None:
            os.environ["AILIT_BASH_SESSION_IDLE_TIMEOUT_MS"] = str(
                int(section.idle_timeout_ms),
            )
        if section.max_sessions is not None:
            os.environ["AILIT_BASH_SESSION_MAX_SESSIONS"] = str(
                int(section.max_sessions),
            )
