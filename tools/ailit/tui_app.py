"""Терминальный чат ailit на Textual (этап P + Q)."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog

from ailit.process_log import ensure_process_log, ProcessLogHandle
from ailit.tui_app_state import TuiAppState
from ailit.tui_context_manager import TuiContextManager
from ailit.tui_slash_registry import SlashCommandRegistry


def resolve_model(provider: str, model: str | None) -> str:
    """Модель по умолчанию в зависимости от провайдера."""
    if model:
        return model
    return "mock" if provider == "mock" else "deepseek-chat"


class AilitTuiApp(App[None]):
    """TUI: slash-команды, мульти-контекст (Q), ``SessionRunner``."""

    BINDINGS = [
        ("ctrl+q", "quit", "Выход"),
        ("ctrl+shift+right", "ctx_next", "След.контекст"),
        ("ctrl+shift+left", "ctx_prev", "Пред.контекст"),
    ]

    def __init__(self, *, args: argparse.Namespace, repo_root: Path) -> None:
        """Сохранить аргументы CLI и корень репозитория ailit-agent."""
        super().__init__()
        self._args = args
        self._repo_root = repo_root
        pr = getattr(args, "project_root", None)
        project_root = Path(str(pr)).resolve() if pr else Path.cwd().resolve()
        prov = str(getattr(args, "provider", "mock"))
        model = resolve_model(prov, getattr(args, "model", None))
        mt = int(getattr(args, "max_turns", 8))
        mgr = TuiContextManager(
            default_root=project_root,
            default_name="default",
        )
        self._app_state = TuiAppState(
            provider=prov,
            model=model,
            max_turns=mt,
            contexts=mgr,
        )
        self._slash = SlashCommandRegistry()
        self._log_handle: ProcessLogHandle | None = None
        self.title = "ailit tui"
        self.sub_title = str(project_root)

    def compose(self) -> ComposeResult:
        """Шапка, журнал, ввод, подвал."""
        yield Header()
        yield RichLog(id="chat_log", wrap=True, highlight=True)
        yield Input(
            id="chat_input",
            placeholder="Сообщение или /help …",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Лог процесса, фокус, подзаголовок."""
        self._log_handle = ensure_process_log("chat")
        self._refresh_subtitle()
        self.query_one("#chat_input", Input).focus()

    def _refresh_subtitle(self) -> None:
        """Активный контекст и параметры провайдера."""
        s = self._app_state.session_view()
        self.sub_title = (
            f"{self._app_state.contexts.active_name()} | {s.provider} | "
            f"{s.model} | mt={s.max_turns}"
        )

    def action_ctx_next(self) -> None:
        """Следующий контекст; сохранить черновик ввода."""
        self._cycle_context(delta=1)

    def action_ctx_prev(self) -> None:
        """Предыдущий контекст; сохранить черновик ввода."""
        self._cycle_context(delta=-1)

    def _cycle_context(self, *, delta: int) -> None:
        """Переключить контекст с сохранением строки ввода (Q.1)."""
        inp = self.query_one("#chat_input", Input)
        draft = inp.value
        mgr = self._app_state.contexts
        mgr.save_draft(mgr.active_name(), draft)
        if delta > 0:
            mgr.activate_next()
        else:
            mgr.activate_prev()
        inp.value = mgr.peek_draft(mgr.active_name())
        self._refresh_subtitle()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Slash не уходит в LLM; обычный текст — ``SessionRunner``."""
        line = event.value.strip()
        self.query_one("#chat_input", Input).value = ""
        if not line:
            return
        log = self.query_one("#chat_log", RichLog)
        if line.startswith("/"):
            res = self._slash.dispatch(line, self._app_state)
            for ln in res.reply_lines:
                log.write(ln)
            self._refresh_subtitle()
            if res.exit_app:
                self.exit()
            return
        log.write(f"[dim]user>[/dim] {line}")
        handle = self._log_handle
        if handle is None:
            log.write(escape("Лог процесса не инициализирован."))
            return
        chat = self._app_state.contexts.active_chat()
        try:
            text, st, usage = chat.run_user_turn(
                line,
                state=self._app_state.session_view(),
                diag_sink=handle.sink,
                log_path=str(handle.path),
            )
            if usage is not None:
                self._app_state.contexts.record_turn_usage(usage)
            log.write(escape(text))
            if st:
                an = self._app_state.contexts.active_name()
                self.sub_title = f"{an} | {st}"[:220]
            else:
                self._refresh_subtitle()
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            log.write(escape(f"{type(exc).__name__}: {exc}"))


def run_ailit_tui(args: argparse.Namespace, *, repo_root: Path) -> None:
    """Точка входа Textual."""
    AilitTuiApp(args=args, repo_root=repo_root).run()
