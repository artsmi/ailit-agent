# flake8: noqa: E501
"""System-hints для file/KB/shell — chat и TUI (read-6 R0, R4.1)."""

from __future__ import annotations

from typing import Any, Mapping

from agent_core.models import ChatMessage, MessageRole


def memory_kb_first_enabled(cfg: Mapping[str, Any] | None) -> bool:
    """True, если в merge-конфиге включена локальная KB (как в chat registry)."""
    if not isinstance(cfg, Mapping):
        return False
    mem = cfg.get("memory")
    return isinstance(mem, dict) and bool(mem.get("enabled", False))


_FILE_TOOLS_SYSTEM_HINT = (
    "Когда пользователь просит создать или записать файл, обязательно вызови инструмент "
    "write_file с относительным путём внутри рабочего корня и содержимым файла. "
    "Не утверждай, что файл создан, если инструмент не был вызван. "
    "После успешных записей в ответе пользователю перечисли каждый затронутый "
    "относительный путь и операцию (создан / обновлён); по возможности используй "
    "префиксы «+» для нового файла и «~» для изменения существующего."
)

_READ_PROTOCOL_SYSTEM_HINT = (
    "Протокол чтения кода (progressive disclosure, анти-raw-dump): "
    "(1) list_dir/glob_file — только для грубой структуры каталогов, не как замена "
    "поиску по содержимому. "
    "(2) grep (rg) — найти путь и примерно номер строки/контекст. "
    "(3) read_file: всегда с offset и limit для первого чтения длинного файла; "
    "допустимый ориентир 120–200 строк на вызов, дальше уточняй. "
    "(4) Python: по имени функции/класса предпочтительно read_symbol, затем read_file "
    "с range вокруг результата. "
    "(5) Не дублируй один и тот же read_file: если тул пишет «File unchanged since "
    "last read», бери текст из раннего tool result в нити. "
    "(6) Для вопросов вроде «как устроен проект / точки входа» сначала используй знания "
    "сессии (см. отдельную подсказку по KB, если она дана)."
)

_FS_TOOLS_SYSTEM_HINT = (
    "Обзор дерева: list_dir (один уровень) или glob_file (шаблон имён). "
    "read_file — только один текстовый файл, не каталог и не '.'. "
    "Поиск по содержимому: grep (нужен `rg` в PATH); не выдумывай вывод grep. "
    "Следуй протоколу progressive disclosure: grep → read_file с offset и limit, "
    "а не весь файл целиком, если он большой (E2E-M3-01, token-economy / TE рецепт)."
)

_KB_FIRST_AFTER_WRITE_HINT = (
    "Память (KB) и namespace: если в проекте доступны инструменты `kb_search` / "
    "`kb_fetch` и в прошлом/в этом run уже записывались auto-факты (например "
    "`repo_entrypoints`, `repo_tree_root`, метаданные репозитория) — **перед** "
    "широким glob/полным чтением дерева ответь на вопросы уровня «как устроен проект», "
    "`какие точки входа», «дерево каталога» поиском по KB и `kb_fetch` по id, "
    "а обход диска используй, когда в KB нет сигнала или ответа недостаточно."
)

_BASH_TOOLS_SYSTEM_HINT = (
    "Инструмент run_shell выполняет команду через bash -lc только внутри "
    "AILIT_WORK_ROOT. Не утверждай результат команды без вызова run_shell. "
    "Для длинного вывода возможна усечённая сводка и файл под .ailit/. "
    "Политика allow/ask/deny для shell задаётся PermissionEngine в runtime; "
    "в Streamlit-чате при включённом «Shell» она часто ALLOW, но это не "
    "отменяет необходимости реально вызвать инструмент и опираться на его вывод."
)


class ChatToolSystemHintComposer:
    """Фрагменты system для файловых tools, опционально KB-first, и для shell (D.4)."""

    @staticmethod
    def fragments(*, include_kb_first: bool = False) -> list[str]:
        """Порядок: протокол чтения, FS, файлы, опционально KB, затем shell."""
        parts: list[str] = [
            _READ_PROTOCOL_SYSTEM_HINT,
            _FS_TOOLS_SYSTEM_HINT,
            _FILE_TOOLS_SYSTEM_HINT,
        ]
        if include_kb_first:
            parts.append(_KB_FIRST_AFTER_WRITE_HINT)
        parts.append(_BASH_TOOLS_SYSTEM_HINT)
        return parts


def inject_tool_hints_before_first_user(
    runner_msgs: list[ChatMessage],
    *,
    include_kb_first: bool = False,
) -> None:
    """Вставить подсказки одним проходом перед первым USER."""
    frags = ChatToolSystemHintComposer.fragments(
        include_kb_first=include_kb_first,
    )
    if not frags:
        return
    for i, m in enumerate(runner_msgs):
        if m.role is MessageRole.USER:
            for text in reversed(frags):
                runner_msgs.insert(
                    i,
                    ChatMessage(role=MessageRole.SYSTEM, content=text),
                )
            return
