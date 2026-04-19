"""Терминальный чат ailit на Textual (этап P)."""

from __future__ import annotations

import argparse
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog

from ailit.tui_slash_registry import SlashCommandRegistry, TuiSessionState


def resolve_model(provider: str, model: str | None) -> str:
    """Модель по умолчанию в зависимости от провайдера."""
    if model:
        return model
    return "mock" if provider == "mock" else "deepseek-chat"


class AilitTuiApp(App[None]):
    """TUI: slash-команды (P.2) и session loop (P.3)."""

    BINDINGS = [("ctrl+q", "quit", "Выход")]

    def __init__(self, *, args: argparse.Namespace, repo_root: Path) -> None:
        """Сохранить аргументы CLI и корень репозитория ailit-agent."""
        super().__init__()
        self._args = args
        self._repo_root = repo_root
        pr = getattr(args, "project_root", None)
        self._project_root = (
            Path(str(pr)).resolve() if pr else Path.cwd().resolve()
        )
        prov = str(getattr(args, "provider", "mock"))
        model = resolve_model(prov, getattr(args, "model", None))
        mt = int(getattr(args, "max_turns", 8))
        self._session = TuiSessionState(
            project_root=self._project_root,
            provider=prov,
            model=model,
            max_turns=mt,
        )
        self._slash = SlashCommandRegistry()
        self.title = "ailit tui"
        self.sub_title = str(self._project_root)

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
        """Фокус и подзаголовок."""
        self._refresh_subtitle()
        self.query_one("#chat_input", Input).focus()

    def _refresh_subtitle(self) -> None:
        """Краткий статус: провайдер, модель, max_turns."""
        s = self._session
        self.sub_title = f"{s.provider} | {s.model} | mt={s.max_turns}"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Slash-команды не уходят в LLM."""
        line = event.value.strip()
        self.query_one("#chat_input", Input).value = ""
        if not line:
            return
        log = self.query_one("#chat_log", RichLog)
        if line.startswith("/"):
            res = self._slash.dispatch(line, self._session)
            for ln in res.reply_lines:
                log.write(ln)
            self._refresh_subtitle()
            if res.exit_app:
                self.exit()
            return
        log.write(f"[dim]user>[/dim] {line}")
        log.write("[yellow]Обычный текст: этап P.3 — SessionRunner[/yellow]")


def run_ailit_tui(args: argparse.Namespace, *, repo_root: Path) -> None:
    """Точка входа Textual."""
    AilitTuiApp(args=args, repo_root=repo_root).run()
