"""Реестр slash-команд для ``ailit tui`` (этап P.2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class TuiSessionState:
    """Изменяемое состояние сессии TUI (модель, лимиты, корень)."""

    project_root: Path
    provider: str
    model: str
    max_turns: int


@dataclass(frozen=True, slots=True)
class SlashDispatchResult:
    """Итог разбора строки, начинающейся с ``/``."""

    consumed: bool
    reply_lines: tuple[str, ...]
    exit_app: bool = False


class SlashCommandHandler(Protocol):
    """Обработчик одной команды (без ведущего ``/``)."""

    def run(self, arg: str, state: TuiSessionState) -> tuple[str, ...]:
        """Строки ответа в журнал."""
        ...


class HelpSlashHandler:
    """Справка по slash-командам."""

    def run(self, arg: str, state: TuiSessionState) -> tuple[str, ...]:
        """Перечень команд и текущие значения."""
        return (
            "Команды: /help | /model [имя] | /max_turns N | "
            "/project [путь] | /quit",
            (
                f"provider={state.provider} model={state.model} "
                f"max_turns={state.max_turns}"
            ),
            f"project_root={state.project_root}",
        )


class ModelSlashHandler:
    """Показать или задать имя модели (локально для сессии)."""

    def run(self, arg: str, state: TuiSessionState) -> tuple[str, ...]:
        """Обновить ``state.model`` при непустом аргументе."""
        name = arg.strip()
        if not name:
            return (f"model={state.model}",)
        state.model = name
        return (f"model={state.model} (сессия)",)


class MaxTurnsSlashHandler:
    """Показать или задать ``max_turns``."""

    def run(self, arg: str, state: TuiSessionState) -> tuple[str, ...]:
        """Парсинг целого N."""
        raw = arg.strip()
        if not raw:
            return (f"max_turns={state.max_turns}",)
        try:
            n = int(raw)
        except ValueError:
            return (f"Ожидалось целое число, получено: {raw!r}",)
        if n < 1:
            return ("max_turns должен быть >= 1",)
        state.max_turns = n
        return (f"max_turns={state.max_turns}",)


class ProjectSlashHandler:
    """Показать или сменить корень проекта."""

    def run(self, arg: str, state: TuiSessionState) -> tuple[str, ...]:
        """Путь существующего каталога."""
        raw = arg.strip()
        if not raw:
            return (f"project_root={state.project_root}",)
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            return (f"Не каталог: {path}",)
        state.project_root = path
        return (f"project_root={state.project_root}",)


class QuitSlashHandler:
    """Выход из TUI."""

    def run(self, arg: str, state: TuiSessionState) -> tuple[str, ...]:
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

    def dispatch(
        self,
        line: str,
        state: TuiSessionState,
    ) -> SlashDispatchResult:
        """Разобрать строку, начинающуюся с ``/``."""
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
        handler = self._handlers.get(name)
        if handler is None:
            return SlashDispatchResult(
                consumed=True,
                reply_lines=(
                    f"Неизвестная команда: /{name}. См. /help",
                ),
                exit_app=False,
            )
        lines = handler.run(arg, state)
        exit_app = name == "quit"
        return SlashDispatchResult(
            consumed=True,
            reply_lines=tuple(lines),
            exit_app=exit_app,
        )
