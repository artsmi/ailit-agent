"""Удаление утечек служебной разметки (DSML и аналоги) из текста ассистента."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _DsmlRegexBundle:
    """Скомпилированные шаблоны для DSML-подобных блоков в content."""

    balanced_block: re.Pattern[str]
    orphan_tail: re.Pattern[str]
    invoke_block: re.Pattern[str]
    function_calls_block: re.Pattern[str]

    @classmethod
    def default(cls) -> _DsmlRegexBundle:
        """Паттерны по утечкам (`<｜DSML｜…>`, `<|DSML|…>`, nested invoke)."""
        # Закрытие: `</DSML>` или `</｜DSML｜…>` (｜ допускается после /).
        close_dsml = r"<\s*/\s*(?:\uFF5c|\|)?\s*DSML[^>]*>"
        balanced = re.compile(
            r"<\s*(?:\uFF5c|\|)?\s*DSML[^>]*>[\s\S]*?" + close_dsml,
            re.IGNORECASE | re.DOTALL,
        )
        orphan = re.compile(
            r"<\s*(?:\uFF5c|\|)?\s*DSML[\s\S]*\Z",
            re.IGNORECASE | re.DOTALL,
        )
        close_invoke = r"<\s*/\s*(?:\uFF5c|\|)?\s*DSML[^>]*\binvoke\b[^>]*>"
        invoke_block = re.compile(
            r"<\s*(?:\uFF5c|\|)?\s*DSML[^>]*\binvoke\b[^>]*>[\s\S]*?"
            + close_invoke,
            re.IGNORECASE | re.DOTALL,
        )
        close_fc = (
            r"<\s*/\s*(?:\uFF5c|\|)?\s*DSML[^>]*\bfunction_calls\b[^>]*>"
        )
        function_calls_block = re.compile(
            r"<\s*(?:\uFF5c|\|)?\s*DSML[^>]*\bfunction_calls\b[^>]*>"
            r"[\s\S]*?"
            + close_fc,
            re.IGNORECASE | re.DOTALL,
        )
        return cls(
            balanced_block=balanced,
            orphan_tail=orphan,
            invoke_block=invoke_block,
            function_calls_block=function_calls_block,
        )


class DsmlLeakStripper:
    """Снимает блоки DSML (дублирование tool_calls в content)."""

    def __init__(self, bundle: _DsmlRegexBundle | None = None) -> None:
        """Инициализировать набором паттернов."""
        self._bundle = bundle or _DsmlRegexBundle.default()

    def strip(self, text: str, *, aggressive_trailing: bool) -> str:
        """Удалить DSML; aggressive_trailing — срезать незакрытый хвост."""
        if not text:
            return text
        cleaned = text
        for _ in range(128):
            old = cleaned
            cleaned = self._bundle.invoke_block.sub("", cleaned)
            cleaned = self._bundle.function_calls_block.sub("", cleaned)
            cleaned = self._bundle.balanced_block.sub("", cleaned)
            if cleaned == old:
                break
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
        """Очистить текст ассистента для UI."""
        return cls._stripper.strip(
            text,
            aggressive_trailing=aggressive_trailing,
        )
