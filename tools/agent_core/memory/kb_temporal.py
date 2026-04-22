"""Вспомогательные правила временной валидности для KB (M3-3)."""

from __future__ import annotations


def sql_active_temporal(now_iso: str) -> tuple[str, tuple[str, ...]]:
    """Фрагмент SQL и параметры: запись «активна» в момент now_iso.

    Активна, если нет верхней границы или она в будущем, и нет нижней
    или она в прошлом/сейчас (сравнение лексикографически для ISO-8601 UTC).
    """
    clause = (
        "("
        " (valid_from IS NULL OR TRIM(COALESCE(valid_from, '')) = '' "
        " OR valid_from <= ?)"
        " AND "
        " (valid_to IS NULL OR TRIM(COALESCE(valid_to, '')) = '' "
        " OR valid_to > ?)"
        ")"
    )
    return clause, (now_iso, now_iso)
