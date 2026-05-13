"""Человекочитаемые тексты по результату session loop для UI ``ailit chat``."""

from __future__ import annotations

MAX_TURNS_EXCEEDED_REASON: str = "max_turns_exceeded"
CAP_FINALIZE_FAILED_REASON: str = "cap_finalize_failed"


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
        if reason == CAP_FINALIZE_FAILED_REASON:
            return (
                "лимит шагов сессии: не удалось получить автоматическое "
                "текстовое резюме после финального вызова модели"
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
        """Тело сообщения при max_turns_exceeded (устаревший путь ядра)."""
        return (
            "**Лимит шагов сессии (устаревший код ошибки).** В актуальном "
            "ядре при исчерпании **max_turns** выполняется дополнительный "
            "text-only вызов модели, чтобы вы получили резюме, а не только "
            "технический `reason`.\n\n"
            "- Если вы видите это сообщение, вероятен внешний исполнитель "
            "или старая версия `agent_core`.\n"
            f"- Лимит в настройках UI/CLI был **{effective_max_turns}** "
            "шаг(ов); при необходимости задайте больший **max_turns** или "
            "проверьте переменную окружения **AILIT_AGENT_HARD_CAP**.\n"
            "- Подробная диагностика: JSONL-лог процесса "
            f"`{log_path}` (события `session.turn`, `session.cap_hit`, …)."
        )

    def _generic_body(self, *, detail: str, log_path: str) -> str:
        """Стандартное сообщение об ошибке модели / цикла."""
        return (
            "Не удалось получить ответ модели. "
            f"Подробности: `{detail}`. См. JSONL-лог процесса: `{log_path}`."
        )
