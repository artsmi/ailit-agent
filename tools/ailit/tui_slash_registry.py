"""Реестр slash-команд для ``ailit tui`` (P.2 + Q.1)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from ailit.config_secrets import ConfigSecretRedactor
from ailit.config_store import apply_config_set
from ailit.merged_config import load_merged_ailit_config
from ailit.tui_app_state import TuiAppState
from ailit.tui_context_persistence import default_state_path, save_app_state
from ailit.tui_context_stats import CtxUsageMarkdownTable
from ailit.user_paths import GlobalDirResolver


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
            "Команды: /help | /model | /max_turns | /project | /cd | /paths | "
            "/config … | /quit | /ctx …",
            "/ctx list | /ctx new NAME [ROOT] | /ctx switch NAME | "
            "/ctx rename NAME | /ctx stats | /ctx save [PATH]",
            "/config show | /config set KEY VALUE",
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


class PathsSlashHandler:
    """Глобальные пути и активный корень (аналог ``ailit config path``)."""

    def run(self, _arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Печать резолвера и ``project_root`` активного контекста."""
        r = GlobalDirResolver(os.environ)
        ah = os.environ.get("AILIT_HOME", "")
        sv = app_state.session_view()
        st = r.global_state_dir()
        return (
            f"AILIT_HOME={ah or '(не задан)'}",
            f"global_config_dir={r.global_config_dir()}",
            f"global_state_dir={st}",
            f"global_logs_dir={st / 'logs'}",
            f"active project_root={sv.project_root}",
        )


class ConfigSlashHandler:
    """Показать/изменить глобальную конфигурацию (DP-2.5)."""

    def run(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """`/config show` или `/config set KEY VALUE`."""
        tokens = arg.strip().split(maxsplit=2)
        if not tokens:
            return ("Использование: /config show | /config set KEY VALUE",)
        sub = tokens[0].lower()
        if sub == "show":
            proj = app_state.session_view().project_root
            merged = dict(load_merged_ailit_config(proj))
            safe = ConfigSecretRedactor().redact(merged)
            text = yaml.safe_dump(safe, allow_unicode=True, sort_keys=False)
            lines = text.strip().splitlines() if text.strip() else ["(пусто)"]
            return ("Эффективный merge (секреты замаскированы):", *lines)
        if sub == "set":
            if len(tokens) < 3:
                return ("Нужно: /config set KEY VALUE",)
            key, value = tokens[1], tokens[2]
            try:
                written = apply_config_set(key, value)
            except ValueError as exc:
                return (str(exc),)
            return (f"Записано в {written}",)
        return ("Использование: /config show | /config set KEY VALUE",)


class SlashCommandRegistry:
    """Регистрация и диспетчеризация команд ``/name``."""

    def __init__(self) -> None:
        """Стандартные обработчики."""
        _project = ProjectSlashHandler()
        self._handlers: dict[str, SlashCommandHandler] = {
            "help": HelpSlashHandler(),
            "model": ModelSlashHandler(),
            "max_turns": MaxTurnsSlashHandler(),
            "project": _project,
            "cd": _project,
            "paths": PathsSlashHandler(),
            "config": ConfigSlashHandler(),
            "quit": QuitSlashHandler(),
        }

    def _handle_ctx(self, arg: str, app_state: TuiAppState) -> tuple[str, ...]:
        """Подкоманды ``/ctx`` (Q.1)."""
        tokens = arg.strip().split()
        if not tokens:
            return (
                "Использование: /ctx list | /ctx new NAME [ROOT] | "
                "/ctx switch NAME | /ctx rename NAME | /ctx stats | "
                "/ctx save [PATH]",
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
        if sub == "save":
            if len(tokens) > 1:
                path = Path(tokens[1]).expanduser()
            else:
                path = default_state_path()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                save_app_state(path, app_state)
            except OSError as exc:
                return (f"Не удалось сохранить: {exc}",)
            return (f"Состояние TUI записано: {path}",)
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
