"""Ошибки транспорта и разбора ответов провайдера."""


class TransportHttpError(RuntimeError):
    """HTTP уровень: статус, тело ответа."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body_snippet: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body_snippet = body_snippet


class MalformedProviderResponseError(ValueError):
    """Ответ провайдера не JSON или неожиданная структура."""
