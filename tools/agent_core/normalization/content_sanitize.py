"""Удаление утечек служебной разметки (DSML и аналоги) из текста ассистента."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _DsmlRegexBundle:
    """Скомпилированные шаблоны для DSML-подобных блоков в content."""

    balanced_block: re.Pattern[str]
    orphan_tail: re.Pattern[str]

    @classmethod
    def default(cls) -> _DsmlRegexBundle:
        """Паттерны по наблюдаемым утечкам (`<｜DSML｜…>`, `<|DSML|…>`)."""
        balanced = re.compile(
            r"<\s*(?:\uFF5c|\|)?\s*DSML[^>]*>[\s\S]*?"
            r"<\s*(?:\uFF5c|\|)?\s*/\s*DSML[^>]*>",
            re.IGNORECASE | re.DOTALL,
        )
        orphan = re.compile(
            r"<\s*(?:\uFF5c|\|)?\s*DSML[\s\S]*\Z",
            re.IGNORECASE | re.DOTALL,
        )
        return cls(balanced_block=balanced, orphan_tail=orphan)


class DsmlLeakStripper:
    """Снимает из текста блоки DSML (дублирование tool_calls в поле content)."""

    def __init__(self, bundle: _DsmlRegexBundle | None = None) -> None:
        """Инициализировать набором паттернов."""
        self._bundle = bundle or _DsmlRegexBundle.default()

    def strip(self, text: str, *, aggressive_trailing: bool) -> str:
        """Удалить DSML; при aggressive_trailing — от незакрытого тега до конца строки."""
        if not text:
            return text
        cleaned = self._bundle.balanced_block.sub("", text)
        prev: str | None = None
        while prev != cleaned:
            prev = cleaned
            cleaned = self._bundle.balanced_block.sub("", cleaned)
        if aggressive_trailing:
            match = self._bundle.orphan_tail.search(cleaned)
            if match is not None:
                cleaned = cleaned[: match.start()].rstrip()
        return cleaned.strip()


class AssistantContentSanitizer:
    """Единая точка очистки ассистентского текста для UI и истории."""

    _stripper = DsmlLeakStripper()

    @classmethod
    def sanitize(cls, text: str, *, aggressive_trailing: bool) -> str:
        """Очистить видимый текст; aggressive_trailing — срезать хвост от незакрытого DSML до конца."""
        return cls._stripper.strip(text, aggressive_trailing=aggressive_trailing)
