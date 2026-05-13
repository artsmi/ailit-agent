"""Глобальные фрагменты стиля ассистента (чат, TUI, workflow).

Единая точка для правил вроде «без эмодзи» и отчёта по путям после
изменения файлов — чтобы не дублировать строки в chat_app / TUI / bootstrap.
"""

from __future__ import annotations


def global_style_system_fragments() -> tuple[str, ...]:
    """Короткие system-абзацы, добавляемые к базовому промпту."""
    return (
        "Не используй эмодзи, эмодзиконы и символы-пиктограммы в ответах.",
        (
            "Когда создаёшь, изменяешь или удаляешь файлы через инструменты, "
            "в пользовательском тексте явно перечисляй относительные пути "
            "(от корня рабочего каталога) и тип операции: создан, обновлён, "
            "удалён. По возможности группируй несколько вызовов write_file "
            "в одном раунде инструментов, пока задача не завершена."
        ),
    )


def merge_with_base_system(base: str) -> str:
    """Склеить базовый system-текст и глобальные стилевые фрагменты."""
    parts = (base.strip(),) + global_style_system_fragments()
    return "\n\n".join(p for p in parts if p.strip())


def workflow_style_append_fragments() -> tuple[str, ...]:
    """Фрагменты для augmentation workflow (без дублирования default)."""
    return global_style_system_fragments()
