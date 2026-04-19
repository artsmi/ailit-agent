"""Реестр slash-команд для ``ailit tui`` (P.2 + Q.1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ailit.tui_app_state import TuiAppState
from ailit.tui_context_stats import CtxUsageMarkdownTable


@dataclass(frozen=True, slots=True)
class SlashDispatchResult:
    """Итог разбора строки, начинающейся с ``/``."""

    consumed: bool
    reply_lines: tuple[str, ...]
    exit_app: bool = False


class SlashCommandHandler(Protocol):
    """Обработчик одной команды (без ведущего ``/``)."""

    def run(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Строки ответа в журнал."""
        ...


class HelpSlashHandler:
    """Справка по slash-командам."""

    def run(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Перечень команд и текущие значения."""
        sv = app_state.session_view()
        return (
            "Команды: /help | /model | /max_turns | /project | /quit | /ctx …",
            "/ctx list | /ctx new NAME [ROOT] | /ctx switch NAME | "
            "/ctx rename NAME | /ctx stats",
            "Горячие клавиши: Ctrl+Shift+Right/Left — смена контекста "
            "(черновик в строке ввода сохраняется).",
            (
                f"provider={sv.provider} model={sv.model} "
                f"max_turns={sv.max_turns}"
            ),
            f"active_ctx={app_state.contexts.active_name()} "
            f"project_root={sv.project_root}",
        )


class ModelSlashHandler:
    """Показать или задать имя модели."""

    def run(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Обновить ``app_state.model`` при непустом аргументе."""
        name = arg.strip()
        if not name:
            return (f"model={app_state.model}",)
        app_state.model = name
        return (f"model={app_state.model} (сессия)",)


class MaxTurnsSlashHandler:
    """Показать или задать ``max_turns``."""

    def run(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Парсинг целого N."""
        raw = arg.strip()
        if not raw:
            return (f"max_turns={app_state.max_turns}",)
        try:
            n = int(raw)
        except ValueError:
            return (f"Ожидалось целое число, получено: {raw!r}",)
        if n < 1:
            return ("max_turns должен быть >= 1",)
        app_state.max_turns = n
        return (f"max_turns={app_state.max_turns}",)


class ProjectSlashHandler:
    """Показать или сменить корень проекта активного контекста."""

    def run(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Путь существующего каталога."""
        raw = arg.strip()
        if not raw:
            return (f"project_root={app_state.session_view().project_root}",)
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            return (f"Не каталог: {path}",)
        app_state.contexts.set_active_project_root(path)
        return (f"project_root={app_state.session_view().project_root}",)


class QuitSlashHandler:
    """Выход из TUI."""

    def run(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Сигнал обрабатывается в приложении."""
        return ("Выход…",)


class SlashCommandRegistry:
    """Регистрация и диспетчеризация команд ``/name``."""

    def __init__(self) -> None:
        """Стандартные обработчики."""
        self._handlers: dict[str, SlashCommandHandler] = {
            "help": HelpSlashHandler(),
            "model": ModelSlashHandler(),
            "max_turns": MaxTurnsSlashHandler(),
            "project": ProjectSlashHandler(),
            "quit": QuitSlashHandler(),
        }

    def _handle_ctx(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Подкоманды ``/ctx`` (Q.1)."""
        tokens = arg.strip().split()
        if not tokens:
            return (
                "Использование: /ctx list | /ctx new NAME [ROOT] | "
                "/ctx switch NAME | /ctx rename NAME | /ctx stats",
            )
        sub = tokens[0].lower()
        mgr = app_state.contexts
        if sub == "list":
            lines = [f"Активный: {mgr.active_name()}", "Контексты:"]
            for n, pr, is_act in mgr.describe_contexts():
                mark = " (активен)" if is_act else ""
                lines.append(f"  - {n}{mark} → {pr}")
            return tuple(lines)
        if sub == "stats":
            return CtxUsageMarkdownTable().render_lines(mgr)
        if sub == "new":
            if len(tokens) < 2:
                return ("Нужно имя: /ctx new NAME [ROOT]",)
            name = tokens[1]
            root: Path | None = None
            if len(tokens) > 2:
                root = Path(tokens[2]).expanduser().resolve()
            err = mgr.new_context(name, project_root=root)
            if err:
                return (err,)
            return (f"Создан контекст `{name}`.",)
        if sub == "switch":
            if len(tokens) < 2:
                return ("Нужно имя: /ctx switch NAME",)
            err = mgr.switch(tokens[1])
            if err:
                return (err,)
            return (f"Активен контекст `{mgr.active_name()}`.",)
        if sub == "rename":
            if len(tokens) < 2:
                return ("Нужно новое имя: /ctx rename NAME",)
            err = mgr.rename_active(tokens[1])
            if err:
                return (err,)
            return (f"Контекст переименован в `{mgr.active_name()}`.",)
        return (f"Неизвестная подкоманда ctx: {sub}. См. /ctx",)

    def dispatch(
        self,
        line: str,
        app_state: TuiAppState,
    ) -> SlashDispatchResult:
        """Разобрать строку со слешем."""
        trimmed = line.strip()
        if not trimmed.startswith("/"):
            return SlashDispatchResult(
                consumed=False,
                reply_lines=(),
                exit_app=False,
            )
        body = trimmed[1:]
        if not body:
            return SlashDispatchResult(
                consumed=True,
                reply_lines=("Пустая команда. Введите /help",),
                exit_app=False,
            )
        parts = body.split(maxsplit=1)
        name = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if name == "ctx":
            lines = self._handle_ctx(arg, app_state)
            return SlashDispatchResult(
                consumed=True,
                reply_lines=lines,
                exit_app=False,
            )
        handler = self._handlers.get(name)
        if handler is None:
            return SlashDispatchResult(
                consumed=True,
                reply_lines=(
                    f"Неизвестная команда: /{name}. См. /help",
                ),
                exit_app=False,
            )
        lines = handler.run(arg, app_state)
        exit_app = name == "quit"
        return SlashDispatchResult(
            consumed=True,
            reply_lines=tuple(lines),
            exit_app=exit_app,
        )
