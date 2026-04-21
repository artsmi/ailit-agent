"""Терминальный чат ailit на Textual (этап P + Q)."""

from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Header, Input, RichLog, Static
from textual.worker import Worker, WorkerState

from ailit.process_log import ensure_process_log, ProcessLogHandle
from ailit.tui_app_state import TuiAppState
from ailit.tui_context_manager import TuiContextManager
from ailit.tui_context_persistence import (
    default_state_path,
    load_app_state,
    save_app_state,
)
from ailit.defaults_resolver import DefaultProviderModelResolver
from ailit.tui_context_stats import TuiSubtitleUsageFormatter
from ailit.tui_slash_registry import SlashCommandRegistry
from ailit.chat_transcript_view import (
    format_assistant_body_for_ui,
    format_tool_summary_markdown,
)
from ailit.tui_llm_worker import TuiLlmTurnOutcome, TuiThreadUiSessionSink
from ailit.tui_transcript_presenter import TuiTranscriptEventPresenter
_LLM_WORKER_NAME = "ailit_llm_turn"


def resolve_model(provider: str, model: str | None) -> str:
    """Модель по умолчанию в зависимости от провайдера."""
    if model:
        return model
    if provider == "mock":
        return "mock"
    if provider == "kimi":
        return "moonshot-v1-8k"
    return "deepseek-chat"


class AilitTuiApp(App[None]):
    """TUI: slash-команды, мульти-контекст (Q), ``SessionRunner``."""

    # Плотность и рамки; кегль шрифта задаётся терминалом, не приложением.
    CSS = """
    #tui_step_pulse {
        height: 1;
        min-height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #tui_stream_preview {
        max-height: 10;
        min-height: 1;
        padding: 0 1;
        border-bottom: tall $boost;
    }
    RichLog {
        height: 1fr;
        border: tall $secondary 30%;
        padding: 0 1;
        margin: 0 1;
    }
    Input {
        dock: bottom;
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Выход"),
        ("ctrl+shift+right", "ctx_next", "След.контекст"),
        ("ctrl+shift+left", "ctx_prev", "Пред.контекст"),
        ("ctrl+m", "mouse_toggle", "Мышь: on/off"),
    ]

    def __init__(self, *, args: argparse.Namespace, repo_root: Path) -> None:
        """Сохранить аргументы CLI и корень репозитория ailit-agent."""
        super().__init__()
        try:
            # По умолчанию: без mouse reporting, для выделения мышью.
            self.disable_mouse()
        except Exception:
            pass
        self._args = args
        self._repo_root = repo_root
        pr = getattr(args, "project_root", None)
        project_root = Path(str(pr)).resolve() if pr else Path.cwd().resolve()
        dflt = DefaultProviderModelResolver().resolve(
            project_root=project_root,
        )
        prov = str(getattr(args, "provider", None) or dflt.provider)
        model = resolve_model(prov, getattr(args, "model", None) or dflt.model)
        mt = int(getattr(args, "max_turns", 10_000))
        self._project_root = project_root
        mgr = TuiContextManager(
            default_root=project_root,
            default_name="default",
        )
        bash_flag = bool(getattr(args, "bash_tools", False))
        self._app_state = TuiAppState(
            provider=prov,
            model=model,
            max_turns=mt,
            contexts=mgr,
            bash_tools=bash_flag,
        )
        self._subtitle_fmt = TuiSubtitleUsageFormatter()
        self._slash = SlashCommandRegistry()
        self._tui_events = TuiTranscriptEventPresenter()
        self._log_handle: ProcessLogHandle | None = None
        self.title = "ailit tui"
        self.sub_title = str(project_root)

    def compose(self) -> ComposeResult:
        """Шапка, строка шага, превью ответа, журнал, ввод."""
        yield Header(show_clock=False)
        yield Static(" ", id="tui_step_pulse")
        yield Static(" ", id="tui_stream_preview")
        yield RichLog(id="chat_log", wrap=True, highlight=True)
        yield Input(
            id="chat_input",
            placeholder="Сообщение или /help …",
        )

    def on_mount(self) -> None:
        """Лог, фокус, подзаголовок; восстановление снимка TUI (Q.3)."""
        self._set_mouse_capture(enabled=False)
        self._log_handle = ensure_process_log("chat")
        bundle = load_app_state(
            default_state_path(),
            default_root=self._project_root,
        )
        if bundle is not None:
            mgr, _sp, _sm, _mt = bundle
            bash_flag = self._app_state.bash_tools
            self._app_state = TuiAppState(
                provider=self._app_state.provider,
                model=self._app_state.model,
                max_turns=self._app_state.max_turns,
                contexts=mgr,
                bash_tools=bash_flag,
            )
        self._refresh_subtitle()
        self.query_one("#chat_input", Input).focus()

    def on_ready(self) -> None:
        """Повторить отключение мыши после инициализации драйвера."""
        self._set_mouse_capture(enabled=False)

    def _set_mouse_capture(self, *, enabled: bool) -> None:
        """Вкл/выкл захват мыши для выделения/копирования в терминале."""
        try:
            if enabled:
                self.enable_mouse()
            else:
                self.disable_mouse()
        except AttributeError:
            # Совместимость с разными версиями Textual.
            try:
                self.mouse_enabled = bool(  # type: ignore[attr-defined]
                    enabled
                )
            except Exception:
                return

    def action_mouse_toggle(self) -> None:
        """Переключить захват мыши для выделения мышью в терминале."""
        cur = getattr(self, "mouse_enabled", True)
        self._set_mouse_capture(enabled=not bool(cur))

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

    def _tui_clear_live_widgets(self) -> None:
        """Очистить однострочный статус шага и превью стрима."""
        for wid in ("#tui_step_pulse", "#tui_stream_preview"):
            try:
                self.query_one(wid, Static).update(" ")
            except Exception:
                pass

    def _tui_step_widget(self, body: object) -> None:
        """Одна «мигающая» строка: модель или инструмент."""
        try:
            self.query_one("#tui_step_pulse", Static).update(body)
        except Exception:
            pass

    def _tui_preview_str(self, body: str) -> None:
        """Превью текущего ответа (без записи в RichLog)."""
        cap = body[:8000] if body.strip() else " "
        try:
            self.query_one("#tui_stream_preview", Static).update(escape(cap))
        except Exception:
            pass

    def _ui_session_model_request(self, pl: dict) -> None:
        """UI-поток: событие ``model.request``."""
        self._tui_step_widget(self._tui_events.model_request_line(pl))

    def _ui_session_tool_started(self, pl: dict) -> None:
        """UI-поток: ``tool.call_started``."""
        self._tui_step_widget(self._tui_events.tool_started_line(pl))

    def _ui_session_tool_finished(self, pl: dict) -> None:
        """UI-поток: ``tool.call_finished``."""
        self._tui_step_widget(self._tui_events.tool_finished_line(pl))

    def _ui_session_assistant_joined(self, joined: str) -> None:
        """UI-поток: обновить превью по накопленному тексту стрима."""
        shown = format_assistant_body_for_ui(
            joined,
            aggressive_tail=True,
        )
        self._tui_preview_str(shown)

    def _ui_bash_shell_preview(self, tail: str) -> None:
        """UI-поток: последние строки вывода run_shell (этап E)."""
        self._tui_preview_str(tail if tail.strip() else " ")

    def _blocking_llm_turn(self, line: str) -> TuiLlmTurnOutcome:
        """Полный прогон ``run_user_turn`` в worker-потоке."""
        handle = self._log_handle
        if handle is None:
            return TuiLlmTurnOutcome(
                text="",
                status_line="",
                usage=None,
                turn_tools=[],
                error=RuntimeError("log handle missing"),
            )
        chat = self._app_state.contexts.active_chat()
        sink = TuiThreadUiSessionSink(self)
        try:
            text, st, usage = chat.run_user_turn(
                line,
                state=self._app_state.session_view(),
                diag_sink=handle.sink,
                log_path=str(handle.path),
                event_sink=sink,
            )
            return TuiLlmTurnOutcome(
                text=text,
                status_line=st,
                usage=usage,
                turn_tools=list(sink.turn_tools),
                error=None,
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            return TuiLlmTurnOutcome(
                text="",
                status_line="",
                usage=None,
                turn_tools=list(sink.turn_tools),
                error=exc,
            )

    def _apply_llm_turn_success(self, out: TuiLlmTurnOutcome) -> None:
        """Дописать ответ в журнал (уже в UI-потоке)."""
        log = self.query_one("#chat_log", RichLog)
        if out.error is not None:
            self._tui_clear_live_widgets()
            log.write(escape(f"{type(out.error).__name__}: {out.error}"))
            return
        if out.usage is not None:
            self._app_state.contexts.record_turn_usage(out.usage)
        self._tui_clear_live_widgets()
        summary_md = format_tool_summary_markdown(out.turn_tools)
        log.write(Text.assemble(("AI", "bold green"), ("> ", "bold green")))
        if summary_md.strip():
            try:
                log.write(Text.from_markup(summary_md))
            except Exception:
                log.write(escape(summary_md))
        final_txt = format_assistant_body_for_ui(
            out.text,
            aggressive_tail=True,
        )
        log.write(escape(final_txt if final_txt.strip() else out.text))
        sv = self._app_state.session_view()
        cum = self._app_state.contexts.active_runtime().usage.as_dict()
        self.sub_title = self._subtitle_fmt.format_after_turn(
            context_name=self._app_state.contexts.active_name(),
            last_turn=out.usage,
            cumulative=cum,
            provider=sv.provider,
            model=sv.model,
            max_turns=sv.max_turns,
        )
        if out.status_line:
            log.write(escape(out.status_line))

    @on(Worker.StateChanged)
    def _on_llm_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Завершение worker: вывести ответ и вернуть ввод."""
        w = event.worker
        if w.name != _LLM_WORKER_NAME:
            return
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        inp = self.query_one("#chat_input", Input)
        inp.disabled = False
        if event.state == WorkerState.SUCCESS:
            out = w.result
            if isinstance(out, TuiLlmTurnOutcome):
                self._apply_llm_turn_success(out)
            inp.focus()
            return
        if event.state == WorkerState.ERROR:
            self._tui_clear_live_widgets()
            log = self.query_one("#chat_log", RichLog)
            err = w.error
            if err is not None:
                log.write(escape(f"{type(err).__name__}: {err}"))
            inp.focus()
            return
        self._tui_clear_live_widgets()
        inp.focus()

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
        log.write(
            Text.assemble(
                ("Вы", "bold cyan"),
                ("> ", "bold cyan"),
                (line, ""),
            )
        )
        handle = self._log_handle
        if handle is None:
            log.write(escape("Лог процесса не инициализирован."))
            return
        self._tui_clear_live_widgets()
        inp = self.query_one("#chat_input", Input)
        inp.disabled = True
        self.run_worker(
            partial(self._blocking_llm_turn, line),
            name=_LLM_WORKER_NAME,
            exclusive=True,
            thread=True,
            exit_on_error=False,
        )


def run_ailit_tui(args: argparse.Namespace, *, repo_root: Path) -> None:
    """Точка входа Textual."""
    AilitTuiApp(args=args, repo_root=repo_root).run()
