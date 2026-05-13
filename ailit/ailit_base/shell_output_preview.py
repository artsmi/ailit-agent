"""Превью stdout/stderr shell для Chat/TUI (хвост строк, отдельный view).

Слой без subprocess: UI и план ``ailit-bash-strategy``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TailPreviewConfig:
    """Пороги отображения по умолчанию."""

    tui_tail_lines: int = 4
    chat_inline_tail_lines: int = 4
    detached_min_duration_ms: int = 5_000
    detached_min_total_lines: int = 24
    detached_min_bytes: int = 8_192


class LineSplitter:
    """Нормализация текста в строки без потери пустых срединных строк."""

    @staticmethod
    def split_lines(text: str) -> list[str]:
        """Разбить по ``\\n``; явный split вместо ``splitlines``."""
        if not text:
            return []
        raw = text.split("\n")
        if raw and raw[-1] == "":
            return raw[:-1]
        return raw


class LineTailSelector:
    """Выбор последних N полных строк."""

    @staticmethod
    def last_lines(text: str, max_lines: int) -> str:
        """Последние ``max_lines`` строк; пустые строки сохраняются."""
        if max_lines < 1:
            return ""
        lines = LineSplitter.split_lines(text)
        if not lines:
            return ""
        chunk = lines[-max_lines:]
        return "\n".join(chunk)


class DetachedViewHeuristic:
    """Рекомендация: отдельный view (Chat) или полный экран (TUI)."""

    @staticmethod
    def suggest_detached_view(
        *,
        elapsed_ms: int,
        byte_len: int,
        line_count: int,
        cfg: TailPreviewConfig | None = None,
    ) -> bool:
        """True, если команда считается «тяжёлой» для inline-отображения."""
        c = cfg or TailPreviewConfig()
        if elapsed_ms >= c.detached_min_duration_ms:
            return True
        if byte_len >= c.detached_min_bytes:
            return True
        if line_count >= c.detached_min_total_lines:
            return True
        return False


class MergedStreamsPreview:
    """Склейка stdout/stderr для одной метки в ленте."""

    @staticmethod
    def merge(stdout: str, stderr: str) -> str:
        """Объединить потоки: сначала stdout, затем stderr с префиксом."""
        out = stdout.rstrip("\n")
        err = stderr.rstrip("\n")
        if err and out:
            return f"{out}\n--- stderr ---\n{err}"
        if err:
            return f"--- stderr ---\n{err}"
        return out
