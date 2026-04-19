"""Человекочитаемые тексты по результату session loop для UI ``ailit chat``."""

from __future__ import annotations

MAX_TURNS_EXCEEDED_REASON: str = "max_turns_exceeded"


class OutcomeReasonHumanizer:
    """Краткое описание внутреннего ``reason`` для подписей и workflow."""

    def humanize(self, reason: str | None) -> str | None:
        """Вернуть строку для пользователя или None, если нечего добавить."""
        if reason is None:
            return None
        if reason == MAX_TURNS_EXCEEDED_REASON:
            return (
                "лимит итераций агентского цикла (max_turns) — "
                "это не лимит токенов ответа API"
            )
        return None


class SessionErrorAssistantMessageComposer:
    """Текст ассистента при ``SessionState.ERROR`` и родственных сбоях."""

    def compose(
        self,
        *,
        reason: str | None,
        log_path: str,
        effective_max_turns: int,
    ) -> str:
        """Собрать markdown-текст для вставки в историю чата."""
        if reason == MAX_TURNS_EXCEEDED_REASON:
            return self._max_turns_body(
                log_path=log_path,
                effective_max_turns=effective_max_turns,
            )
        detail = reason or "unknown_error"
        return self._generic_body(detail=detail, log_path=log_path)

    def _max_turns_body(
        self,
        *,
        log_path: str,
        effective_max_turns: int,
    ) -> str:
        """Тело сообщения при max_turns_exceeded."""
        return (
            "**Лимит шагов сессии исчерпан.** Агент успел сделать максимум "
            "итераций «вызов модели → обработка инструментов → повтор», "
            "но не выдал финальный текстовый ответ.\n\n"
            "- Это настройка **max_turns** (лимит итераций **оркестратора**), "
            "она **не** заменяет и **не** дублирует лимит длины одного ответа "
            "у провайдера (**max_tokens** / output tokens), если он задан.\n"
            f"- Сейчас действовал лимит **{effective_max_turns}** шаг(ов). "
            "Увеличьте слайдер **max_turns** в шапке чата или задайте больший "
            "лимит в пресете агента в `project.yaml`.\n"
            "- Подробная диагностика: JSONL-лог процесса "
            f"`{log_path}` (события `session.turn`, `model.request`, …)."
        )

    def _generic_body(self, *, detail: str, log_path: str) -> str:
        """Стандартное сообщение об ошибке модели / цикла."""
        return (
            "Не удалось получить ответ модели. "
            f"Подробности: `{detail}`. См. JSONL-лог процесса: `{log_path}`."
        )
