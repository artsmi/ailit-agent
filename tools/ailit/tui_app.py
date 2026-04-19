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
from ailit.tui_context_persistence import (
    default_state_path,
    load_app_state,
    save_app_state,
)
from ailit.tui_context_stats import TuiSubtitleUsageFormatter
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
        self._project_root = project_root
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
        self._subtitle_fmt = TuiSubtitleUsageFormatter()
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
        """Лог, фокус, подзаголовок; восстановление снимка TUI (Q.3)."""
        self._log_handle = ensure_process_log("chat")
        bundle = load_app_state(
            default_state_path(),
            default_root=self._project_root,
        )
        if bundle is not None:
            mgr, _sp, _sm, _mt = bundle
            self._app_state = TuiAppState(
                provider=self._app_state.provider,
                model=self._app_state.model,
                max_turns=self._app_state.max_turns,
                contexts=mgr,
            )
        self._refresh_subtitle()
        self.query_one("#chat_input", Input).focus()

    def on_unmount(self) -> None:
        """Сохранить контексты и usage перед выходом."""
        try:
            save_app_state(default_state_path(), self._app_state)
        except OSError:
            pass

    def _refresh_subtitle(self) -> None:
        """Активный контекст, Σ по контексту и параметры провайдера (Q.2)."""
        s = self._app_state.session_view()
        cum = self._app_state.contexts.active_runtime().usage.as_dict()
        self.sub_title = self._subtitle_fmt.format_idle(
            context_name=self._app_state.contexts.active_name(),
            cumulative=cum,
            provider=s.provider,
            model=s.model,
            max_turns=s.max_turns,
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
            sv = self._app_state.session_view()
            cum = self._app_state.contexts.active_runtime().usage.as_dict()
            self.sub_title = self._subtitle_fmt.format_after_turn(
                context_name=self._app_state.contexts.active_name(),
                last_turn=usage,
                cumulative=cum,
                provider=sv.provider,
                model=sv.model,
                max_turns=sv.max_turns,
            )
            if st:
                log.write(escape(st))
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            log.write(escape(f"{type(exc).__name__}: {exc}"))


def run_ailit_tui(args: argparse.Namespace, *, repo_root: Path) -> None:
    """Точка входа Textual."""
    AilitTuiApp(args=args, repo_root=repo_root).run()
